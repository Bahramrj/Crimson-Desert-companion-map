"""Read-only position engine for CrimsonDesert.exe.

Ported from CD_Companion (server/memory/*, commit 35aa7f3) with every write
path removed. What is left:

- one capture-only hook on the physics position update (upstream's hook_e
  without its flag branches): the cave copies rbx, r13 and [r13] into our own
  block and bumps a tick counter, then runs the original instructions unchanged;
- a plain read of the world offset.

GameProcess.write() refuses any address that is not our own allocation or the
registered hook site.
"""

import ctypes
import ctypes.wintypes as wt
import logging
import struct
import time

from engine.base import Engine
from engine.models import (
    AOB_NOT_FOUND, ATTACHED, ERROR, WAITING_FOR_GAME, EngineState, realm_for_height,
)
from engine.signatures import find_all, load_signatures, parse_hex
from engine.models import player_heading

log = logging.getLogger("cdlivemap.engine")

PROCESS_NAME = "CrimsonDesert.exe"
RETRY_SECONDS = 2.0       # waiting for the game to start
RESCAN_SECONDS = 10.0     # after aob_not_found / error

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40
NEAR_RANGE = 0x7FF00000   # stay reachable from the hook site with a rel32 jump

# Layout of our block inside the game process
BLOCK_SIZE = 0x1000
MAGIC = b"CDLMAP\x00\x01"
OFF_RBX = 0x08            # physics entity; forward vector at +0x80 / +0x88
OFF_R13 = 0x10            # pointer to the position vector
OFF_TICKS = 0x18          # u32, +1 every time the cave runs
OFF_POS = 0x20            # vec4 copied from [r13]
OFF_CAVE = 0x100
ENTITY_FWD = 0x80

# The cave re-executes these and restores xmm0 to xmm6 afterwards, so it is
# only valid for exactly this instruction pair.
CAVE_ORIGINAL = bytes.fromhex("0F28C6 F3450F5CC8")


class GameNotRunning(Exception):
    pass


class SignatureError(Exception):
    """A required pattern is missing or ambiguous; the game was probably updated."""


class HookConflict(Exception):
    """Another tool already hooks the same code."""


# ── Win32 ────────────────────────────────────────────────────────────

_k32 = None
_ver = None


def _kernel32():
    # Own WinDLL instance so these argtypes never clash with pymem's.
    global _k32
    if _k32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
        k.VirtualAllocEx.restype = ctypes.c_void_p
        k.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
        k.VirtualFreeEx.restype = wt.BOOL
        k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        k.WaitForSingleObject.restype = wt.DWORD
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        k.QueryFullProcessImageNameW.restype = wt.BOOL
        _k32 = k
    return _k32


def _version_dll():
    global _ver
    if _ver is None:
        v = ctypes.WinDLL("version")
        v.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
        v.GetFileVersionInfoSizeW.restype = wt.DWORD
        v.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
        v.GetFileVersionInfoW.restype = wt.BOOL
        v.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT)]
        v.VerQueryValueW.restype = wt.BOOL
        _ver = v
    return _ver


def file_version(path):
    v = _version_dll()
    size = v.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    data = ctypes.create_string_buffer(size)
    if not v.GetFileVersionInfoW(path, 0, size, data):
        return ""
    ptr, length = ctypes.c_void_p(), wt.UINT()
    if not v.VerQueryValueW(data, "\\", ctypes.byref(ptr), ctypes.byref(length)):
        return ""
    # VS_FIXEDFILEINFO: dwSignature, dwStrucVersion, dwFileVersionMS, dwFileVersionLS
    ms, ls = struct.unpack_from("<II", ctypes.string_at(ptr, length.value), 8)
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


class GameProcess:
    """pymem + kernel32 wrapper. Writes only reach our allocations and registered patch sites."""

    def __init__(self, pm, module):
        self.pm = pm
        self.pid = pm.process_id
        self.base = module.lpBaseOfDll
        self.size = module.SizeOfImage
        self._writable = {}   # start address -> size

    @classmethod
    def open(cls, name=PROCESS_NAME):
        import pymem
        import pymem.exception
        import pymem.process
        try:
            pm = pymem.Pymem(name)
        except pymem.exception.ProcessNotFound as e:
            raise GameNotRunning(name) from e
        module = pymem.process.module_from_name(pm.process_handle, name)
        if module is None:
            pm.close_process()
            raise GameNotRunning(f"{name} has no main module yet")
        return cls(pm, module)

    def is_alive(self):
        try:
            return _kernel32().WaitForSingleObject(self.pm.process_handle, 0) != 0
        except Exception:
            return False

    def exe_path(self):
        buf, n = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
        if _kernel32().QueryFullProcessImageNameW(self.pm.process_handle, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""

    def exe_version(self):
        try:
            path = self.exe_path()
            return file_version(path) if path else ""
        except Exception:
            return ""

    def read(self, addr, size):
        return self.pm.read_bytes(addr, size)

    def read_module(self):
        data = bytearray(self.size)
        for off in range(0, self.size, 0x10000):
            n = min(0x10000, self.size - off)
            try:
                data[off:off + n] = self.pm.read_bytes(self.base + off, n)
            except Exception:
                pass
        return bytes(data)

    def alloc(self, size, near=None):
        k, handle = _kernel32(), self.pm.process_handle
        flags = MEM_COMMIT | MEM_RESERVE
        addr = 0
        if near is None:
            addr = k.VirtualAllocEx(handle, None, size, flags, PAGE_EXECUTE_READWRITE) or 0
        else:
            for off in range(0x10000, NEAR_RANGE, 0x10000):
                for cand in (near + off, near - off):
                    if cand > 0:
                        addr = k.VirtualAllocEx(handle, cand, size, flags, PAGE_EXECUTE_READWRITE) or 0
                        if addr:
                            break
                if addr:
                    break
        if addr:
            self._writable[addr] = size
        return addr

    def free(self, addr):
        self._writable.pop(addr, None)
        _kernel32().VirtualFreeEx(self.pm.process_handle, addr, 0, MEM_RELEASE)

    def allow_patch(self, addr, size):
        self._writable[addr] = size

    def write(self, addr, data):
        for start, size in self._writable.items():
            if start <= addr and addr + len(data) <= start + size:
                self.pm.write_bytes(addr, data, len(data))
                return
        raise PermissionError(f"Refusing to write {len(data)} bytes at {addr:#x}: not our block or hook site")

    def close(self):
        try:
            self.pm.close_process()
        except Exception:
            pass


# ── Hook ─────────────────────────────────────────────────────────────

def rel_jmp(src, dst, size):
    rel = dst - (src + 5)
    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise ValueError("jump target out of rel32 range")
    return b"\xE9" + struct.pack("<i", rel) + b"\x90" * (size - 5)


def abs_jmp(target):
    return b"\xFF\x25\x00\x00\x00\x00" + struct.pack("<Q", target)


def build_capture_cave(block, resume):
    """Copy rbx, r13 and [r13] into our block, bump the tick counter, run the
    original instructions and jump back. Writes nothing outside our block and
    leaves every register and RFLAGS as the original code would."""
    c = bytearray()
    c += CAVE_ORIGINAL                              # movaps xmm0,xmm6 ; subss xmm9,xmm8
    c += b"\x50"                                    # push rax
    c += b"\x48\xB8" + struct.pack("<Q", block)     # mov rax, block
    c += b"\x48\x89\x58" + bytes([OFF_RBX])         # mov [rax+OFF_RBX], rbx
    c += b"\x4C\x89\x68" + bytes([OFF_R13])         # mov [rax+OFF_R13], r13
    c += b"\x51"                                    # push rcx
    c += b"\x8B\x48" + bytes([OFF_TICKS])           # mov ecx, [rax+OFF_TICKS]
    c += b"\x8D\x49\x01"                            # lea ecx, [rcx+1]  (lea leaves RFLAGS alone)
    c += b"\x89\x48" + bytes([OFF_TICKS])           # mov [rax+OFF_TICKS], ecx
    c += b"\x59"                                    # pop rcx
    c += b"\x41\x0F\x10\x45\x00"                    # movups xmm0, [r13]
    c += b"\x0F\x11\x40" + bytes([OFF_POS])         # movups [rax+OFF_POS], xmm0
    c += b"\x0F\x28\xC6"                            # movaps xmm0, xmm6  (what the original left in xmm0)
    c += b"\x58"                                    # pop rax
    c += abs_jmp(resume)
    return bytes(c)


class PositionHook:
    def __init__(self, proc, signatures):
        self.proc = proc
        self.sig = signatures["physics_position"]
        self.world_sig = signatures["world_offset"]
        self.original = parse_hex(self.sig["original"])
        if self.original != CAVE_ORIGINAL:
            raise SignatureError("signatures.json changed the hooked instructions; the cave must be updated too")
        self.site = 0
        self.world_offset_addr = 0
        self.block = 0
        self.trampoline = 0
        self.installed = False
        self.results = {}   # signature name -> list of RVAs (at most 2)

    def _log_result(self, name, hits):
        self.results[name] = [f"{h:#x}" for h in hits]
        where = (" at " + ", ".join(self.results[name])) if hits else ""
        count = f">={len(hits)}" if len(hits) > 1 else str(len(hits))
        log.info("AOB %-32s %s match(es)%s", name, count, where)

    def scan(self, recover_patched=True):
        """Resolve the hook site and world offset. With recover_patched=False this never writes."""
        data, base = self.proc.read_module(), self.proc.base

        hits = find_all(data, self.world_sig["pattern"])
        self._log_result("world_offset", hits)
        if len(hits) != 1:
            raise SignatureError(f"world_offset pattern has {len(hits)} matches, need exactly 1")
        i = hits[0]
        disp = struct.unpack_from("<i", data, i + self.world_sig["disp_offset"])[0]
        self.world_offset_addr = base + i + self.world_sig["rip_offset"] + disp

        hits = find_all(data, self.sig["pattern"])
        self._log_result("physics_position", hits)
        if len(hits) > 1:
            raise SignatureError("physics_position pattern is ambiguous")
        if len(hits) == 1:
            self.site = base + hits[0]
            return
        patched = find_all(data, self.sig["patched_pattern"])
        self._log_result("physics_position (patched)", patched)
        if len(patched) != 1:
            raise SignatureError("physics_position pattern not found")
        self.site = base + patched[0]
        if not recover_patched:
            raise SignatureError("physics_position site is already patched (by us or another tool)")
        self._recover_patched_site()

    def _recover_patched_site(self):
        """The site already holds a jump: remove it if it is ours from an earlier session."""
        proc, site = self.proc, self.site
        target = site + 5 + struct.unpack_from("<i", proc.read(site, 5), 1)[0]
        block = tramp = 0
        try:
            head = proc.read(target, 14)
        except Exception:
            head = None
        magic = None
        if head is not None:
            cave = target
            if head[:6] == b"\xFF\x25\x00\x00\x00\x00":
                tramp, cave = target, struct.unpack_from("<Q", head, 6)[0]
            block = cave - OFF_CAVE
            try:
                magic = proc.read(block, len(MAGIC))
            except Exception:
                magic = b""   # mapped jump target that is not our cave: someone else's hook
        if magic is None:
            log.warning("Hook site jumps to unmapped memory; restoring the original bytes")
        elif magic == MAGIC:
            log.warning("Removing our own hook left by an earlier session (block %#x)", block)
        else:
            raise HookConflict("Another tool (OpenFlight, Freedom Flyer, a trainer?) already hooks the "
                               "player physics code. Close it and restart the game.")
        proc.allow_patch(site, len(self.original))
        proc.write(site, self.original)
        if magic == MAGIC:
            time.sleep(0.05)
            for addr in (tramp, block):
                if addr:
                    proc.free(addr)

    def install(self):
        proc, site = self.proc, self.site
        cave_size = len(build_capture_cave(0, 0))
        block = proc.alloc(BLOCK_SIZE, near=site)
        far = not block
        if far:
            block = proc.alloc(BLOCK_SIZE)
            if not block:
                raise RuntimeError("Could not allocate memory in the game process")
        self.block = block
        assert OFF_CAVE + cave_size <= BLOCK_SIZE
        proc.write(block, MAGIC + bytes(OFF_CAVE - len(MAGIC)))
        proc.write(block + OFF_CAVE, build_capture_cave(block, site + self.sig["resume_offset"]))
        jump_to = block + OFF_CAVE
        if far:
            self.trampoline = proc.alloc(64, near=site)
            if not self.trampoline:
                raise RuntimeError("Could not allocate a trampoline near the hook site")
            proc.write(self.trampoline, abs_jmp(jump_to))
            jump_to = self.trampoline
        patch = rel_jmp(site, jump_to, self.sig["patch_size"])
        if proc.read(site, len(self.original)) != self.original:
            raise HookConflict("Hook site changed between scan and install")
        proc.allow_patch(site, len(self.original))
        proc.write(site, patch)
        self.installed = True
        log.info("Capture hook installed at %#x (block %#x, %s)", site, block, "far" if far else "near")

    def uninstall(self):
        if self.installed:
            self.proc.write(self.site, self.original)
            self.installed = False
            time.sleep(0.05)   # let a thread that is inside the cave leave it before freeing
            log.info("Capture hook removed, original bytes restored at %#x", self.site)
        for addr in (self.trampoline, self.block):
            if addr:
                self.proc.free(addr)
        self.block = self.trampoline = 0

    def read_sample(self):
        """(ticks, (x, y, z) in physics space, physics entity pointer)."""
        raw = self.proc.read(self.block + OFF_RBX, OFF_POS + 12 - OFF_RBX)
        rbx, _r13, ticks = struct.unpack_from("<QQI", raw, 0)
        pos = struct.unpack_from("<fff", raw, OFF_POS - OFF_RBX)
        return ticks, pos, rbx

    def read_world_offset(self):
        return struct.unpack("<fff", self.proc.read(self.world_offset_addr, 12))

    def read_heading(self, entity):
        if not entity:
            return None
        try:
            fx, _, fz = struct.unpack("<fff", self.proc.read(entity + ENTITY_FWD, 12))
        except Exception:
            return None
        return player_heading(fx, fz)


# ── Engine ───────────────────────────────────────────────────────────

class MemoryEngine(Engine):
    def __init__(self, process_factory=GameProcess.open, signatures=None, **kwargs):
        super().__init__(**kwargs)
        self._open_process = process_factory
        self._signatures = signatures or load_signatures()
        self._proc = None
        self._hook = None
        self._last_ticks = None
        self._fresh_ts = None
        self.diagnostics = {}

    def _tick(self):
        if self._proc is not None and not self._proc.is_alive():
            log.warning("Game exited")
            self._drop(process_gone=True)

        if self._proc is None:
            try:
                self._proc = self._open_process()
            except GameNotRunning:
                return EngineState(WAITING_FOR_GAME), RETRY_SECONDS
            except Exception as e:
                log.error("Cannot open the game process: %s", e)
                return EngineState(ERROR, message=f"Cannot open the game process ({e}). "
                                                  "Run as administrator."), RESCAN_SECONDS
            version = self._proc.exe_version()
            log.info("Attached to %s pid=%d base=%#x size=%#x version=%s",
                     PROCESS_NAME, self._proc.pid, self._proc.base, self._proc.size, version or "?")
            self.diagnostics = {"pid": self._proc.pid, "game_version": version,
                                "module_size": f"{self._proc.size:#x}"}

        if self._hook is None:
            hook = PositionHook(self._proc, self._signatures)
            try:
                hook.scan()
                hook.install()
            except SignatureError as e:
                self.diagnostics["signatures"] = hook.results
                log.error("%s", e)
                hook.uninstall()
                self._drop()
                return EngineState(AOB_NOT_FOUND, message=f"{e}. The game was probably updated."), RESCAN_SECONDS
            except Exception as e:
                self.diagnostics["signatures"] = hook.results
                log.error("Hook failed: %s", e)
                hook.uninstall()
                self._drop()
                return EngineState(ERROR, message=str(e)), RESCAN_SECONDS
            self._hook, self._last_ticks, self._fresh_ts = hook, None, None
            self.diagnostics.update(signatures=hook.results, block=f"{hook.block:#x}",
                                    far_mode=bool(hook.trampoline))

        try:
            return self._sample(), self.interval
        except Exception as e:
            log.warning("Read failed: %s; re-attaching", e)
            self._drop(process_gone=not self._proc.is_alive())
            return EngineState(ERROR, message=f"Read failed: {e}"), RETRY_SECONDS

    def _sample(self):
        hook = self._hook
        ticks, (px, py, pz), entity = hook.read_sample()
        if ticks == 0:
            return EngineState(ATTACHED, message="Waiting for the game to simulate (paused or loading?)")
        if ticks != self._last_ticks:
            self._last_ticks, self._fresh_ts = ticks, time.time()
        wx, _wy, wz = hook.read_world_offset()
        x, y, z = px + wx, py, pz + wz   # same as upstream get_player_abs
        return EngineState(ATTACHED, x=x, y=y, z=z, realm=realm_for_height(y),
                           heading=hook.read_heading(entity), ts=self._fresh_ts)

    def _drop(self, process_gone=False):
        if self._hook is not None:
            if not process_gone:
                try:
                    self._hook.uninstall()
                except Exception:
                    log.exception("Failed to remove the capture hook")
            self._hook = None
        if self._proc is not None:
            self._proc.close()
            self._proc = None

    def _cleanup(self):
        self._drop(process_gone=self._proc is not None and not self._proc.is_alive())
