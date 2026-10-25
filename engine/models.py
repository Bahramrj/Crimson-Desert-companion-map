"""Engine state model, shared by the memory engine and the simulator."""

import math
from dataclasses import asdict, dataclass

WAITING_FOR_GAME = "waiting_for_game"
ATTACHED = "attached"
AOB_NOT_FOUND = "aob_not_found"
ERROR = "error"
STATUSES = (WAITING_FOR_GAME, ATTACHED, AOB_NOT_FOUND, ERROR)

# Same rule as CD_Companion (server/main.py): the Abyss sits high above Pywel.
ABYSS_HEIGHT_THRESHOLD = 1400.0


def realm_for_height(y):
    return "abyss" if y > ABYSS_HEIGHT_THRESHOLD else "pywel"


def player_heading(fx, fz):
    """Heading in signed degrees (clockwise from +z) from the entity's backward vector (fx, fz);
    the components are negated because entity+0x80/0x88 points backwards."""
    if fx * fx + fz * fz < 1e-6:
        return None
    return math.atan2(-fx, -fz) * 180.0 / math.pi


@dataclass(frozen=True)
class EngineState:
    status: str = WAITING_FOR_GAME
    x: float | None = None          # absolute game coordinates (world offset applied)
    y: float | None = None
    z: float | None = None
    realm: str | None = None        # "pywel" | "abyss"
    heading: float | None = None    # player heading, signed degrees -180..180
    camera_heading: float | None = None
    marker: tuple | None = None     # in-game map marker (x, y, z)
    ts: float | None = None         # wall-clock time of the last fresh game sample
    message: str = ""               # human-readable detail for aob_not_found / error

    def to_dict(self):
        return asdict(self)
