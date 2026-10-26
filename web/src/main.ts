// Device shell (tablet, phone, browser): the local map (local/olBridge.ts) with live tracking, follow mode, realm
// switching, layout profiles and per-map calibration on top. Works fully offline.
import "./styles.css";
import { Api, ApiError, type MapListing, type MapSummary, type Marker, type MarkerListing, type Profile } from "./api";
import type { Bridge, LatLng, MapLayer, MapMarker } from "./bridge";
import { gameToPx, REALMS, type Realm } from "./coord";
import { categoryColor, iconUrl } from "./local/icons";
import { createBridge } from "./local/olBridge";
import { Live, type PositionMsg, type ServerMsg } from "./live";
import { DEFAULT_LAYOUT, loadPrefs, savePrefs, type Layout, type RealmMode } from "./prefs";
import { h, icon, segmented, slider, toggle, type IconName } from "./ui";

const STALE_MS = 2000;
const TICK_MS = 250;
const SOURCE_LABEL = { A: "your game files", B: "download", C: "own capture" } as const;

const SEARCH_LIMIT = 40;
// Panel sections, in this order (gamedata/markers.py GROUPS); other groups follow, "My markers" last.
const GROUP_ORDER = ["Regions", "Locations", "Services", "Activities", "Abyss", "Rest & travel", "Treasures", "Crafting", "Mining", "Gathering"];

type SheetKind = "markers" | "profiles" | "settings";
type ButtonKey = "follow" | "recenter" | "zoomIn" | "zoomOut" | "realm" | "markers" | "profiles" | "settings";

class App {
  private api = new Api(new URLSearchParams(location.search).get("k") ?? "");
  private prefs = loadPrefs();
  private layout: Layout = { ...this.prefs.layout };

  private mapEl = h("div", { id: "map", "data-testid": "map" });
  private pill = h("div", { id: "pill", "data-testid": "pill", role: "status" }, h("span", {}, "Connecting…"));
  private chips = h("div", { id: "chips" });
  private toolbar = h("nav", { id: "toolbar", "aria-label": "Menu" });
  private controls = h("div", { id: "controls", "aria-label": "Map controls", role: "group" });
  private sheet = h("section", { id: "sheet", hidden: true, "aria-live": "polite" });
  private toast = h("div", { id: "toast", hidden: true, role: "alert" });
  private card = h("section", { id: "card", hidden: true, "data-testid": "marker-card", "aria-live": "polite" });
  private buttons = {} as Record<ButtonKey, HTMLButtonElement>;

  private bridge!: Bridge;
  private wsOpen = false;
  private engine = { status: "waiting_for_game", message: "" };
  private pos: PositionMsg | null = null;
  private lastTs: number | null | undefined = undefined;
  private freshAt = 0;
  private shownRealm: Realm = "pywel";
  private askRealm: Realm | null = null;
  /** The user picked the realm the player is not in: no automatic switching until the player
   *  changes realm, or follow / recenter takes the view back to the player. */
  private realmPinned = false;
  private maps: MapListing | null = null;
  private calibrating: Realm | null = null;
  private markerData: MarkerListing | null = null;
  private markerIndex = new Map<string, Marker>();
  private found = new Set<string>();
  private offKeys = new Set<string>();     // categories hidden until switched on
  private selected: string | null = null;
  private addingByTap = false;
  private query = "";
  private profiles: Profile[] = [];
  private defaultProfileId: string | null = null;
  private sheetKind: SheetKind | null = null;
  private toastTimer = 0;
  private live = new Live(this.api.withPin(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/cdlm/ws`), {
    open: () => { this.wsOpen = true; void this.loadMaps(); void this.loadMarkers(); this.render(); },
    close: () => { this.wsOpen = false; this.render(); },
    message: (msg) => this.onMessage(msg),
  });

  async start() {
    this.buildToolbar();
    document.body.append(this.mapEl, this.pill, this.chips, this.controls, this.toolbar, this.sheet, this.card, this.toast);
    this.bridge = createBridge(this.mapEl);
    this.bridge.onUserPan(() => { if (this.layout.follow) this.setFollow(false); });
    this.bridge.onTap((ll, key) => void this.onMapTap(ll, key));
    this.applyLayoutChrome();
    this.bridge.setFollow(this.layout.follow);
    this.bridge.setOpacity(this.layout.mapOpacity, this.layout.markerOpacity);
    this.live.start();
    setInterval(() => this.tick(), TICK_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") { this.live.kick(); void this.keepAwake(); }
    });
    void this.keepAwake();
    await Promise.all([this.loadMaps(), this.loadProfiles(true), this.loadMarkers()]);
    (window as unknown as { cdlmShell: unknown }).cdlmShell = { state: () => this.debugState() };
  }

  // ── toolbar and chrome ─────────────────────────────────────────

  private buildToolbar() {
    const make = (key: ButtonKey, name: IconName, label: string, onclick: () => void, prefix = "tb") => {
      const b = h("button", { type: "button", class: `tb ${key}`, "aria-label": label, title: label, "data-testid": `${prefix}-${key}`, onclick }, icon(name));
      this.buttons[key] = b;
      return b;
    };
    this.toolbar.append(
      make("realm", "realm", "Switch realm", () => this.showRealm(this.shownRealm === "pywel" ? "abyss" : "pywel", true)),
      make("markers", "filters", "Markers", () => this.toggleMarkersSheet()),
      make("profiles", "profiles", "Layout profiles", () => this.openSheet("profiles")),
      make("settings", "settings", "Settings", () => this.openSheet("settings")),
    );
    this.buttons.realm.append(h("span", { class: "badge", "data-testid": "realm-badge" }));
    // on the map: follow / free explore, then zoom in, recenter, zoom out
    const follow = make("follow", "follow", "Follow player", () => this.setFollow(!this.layout.follow), "ctl");
    follow.append(icon("free"), h("span", { class: "caption", "data-testid": "follow-mode" }));
    this.controls.append(follow,
      h("div", { class: "zoom" },
        make("zoomIn", "plus", "Zoom in", () => this.bridge.zoomBy(1), "ctl"),
        make("recenter", "recenter", "Show my position", () => this.recenter(), "ctl"),
        make("zoomOut", "minus", "Zoom out", () => this.bridge.zoomBy(-1), "ctl")));
  }

  private applyLayoutChrome() {
    const root = document.documentElement;
    if (this.layout.theme === "auto") delete root.dataset.theme; else root.dataset.theme = this.layout.theme;
    document.body.dataset.toolbar = this.layout.toolbarSide;
  }

  private saveLayout() {
    this.prefs.layout = { ...this.layout };
    savePrefs(this.prefs);
  }

  private notify(text: string) {
    this.toast.textContent = text;
    this.toast.hidden = false;
    clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => { this.toast.hidden = true; }, 3500);
  }

  // ── maps ───────────────────────────────────────────────────────

  private activeMap(realm: Realm): MapSummary | null {
    const id = this.maps?.active[realm];
    return this.maps?.maps.find((m) => m.id === id) ?? null;
  }

  private layerFor(realm: Realm): MapLayer | null {
    const m = this.activeMap(realm);
    return m && { id: m.id, rev: m.rev, image: m.image, tileSize: m.tileSize, maxZoom: m.maxZoom,
      bounds: m.bounds, tiles: this.api.withPin(m.tiles) };
  }

  private async loadMaps() {
    try {
      this.maps = await this.api.maps();
    } catch (e) {
      this.notify(`Maps not loaded: ${(e as Error).message}`);
      return;
    }
    this.bridge.setMap(this.layerFor(this.shownRealm));
    if (this.sheetKind === "settings") this.renderSheet();
    this.render();
  }

  private showRealm(realm: Realm, manual = false) {
    this.askRealm = null;
    if (manual) this.realmPinned = !!this.pos && this.pos.realm !== realm;
    if (realm === this.shownRealm) return;
    this.shownRealm = realm;
    this.calibrating = null;
    this.bridge.setMap(this.layerFor(realm));
    this.selectMarker(null);
    this.updateMarkers();
    if (manual && this.pos && this.pos.realm !== realm) this.setFollow(false);
    this.updatePlayer();
    if (this.sheetKind === "settings") this.renderSheet();
    this.render();
  }

  // ── live data ──────────────────────────────────────────────────

  private onMessage(msg: ServerMsg) {
    switch (msg.type) {
      case "status":
        this.engine = { status: msg.status, message: msg.message };
        break;
      case "position":
        this.onPosition(msg);
        break;
      case "profile_changed":
        void this.loadProfiles(false);
        break;
      case "map_changed":
        void this.loadMaps();
        break;
      case "markers_changed":
        void this.loadMarkers();
        break;
      case "progress_changed":
        if (msg.found) this.found.add(msg.key); else this.found.delete(msg.key);
        this.updateMarkers();
        break;
    }
    this.render();
  }

  private onPosition(msg: PositionMsg) {
    if (msg.ts !== this.lastTs) {
      this.lastTs = msg.ts;
      this.freshAt = performance.now();
    }
    const realmChanged = this.pos?.realm !== msg.realm;
    this.pos = msg;
    if (realmChanged) this.realmPinned = false;           // the player moved realm: follow them again
    if (msg.realm !== this.shownRealm) {
      if (this.realmPinned) { /* the user is looking at the other realm on purpose */ }
      else if (this.prefs.realmMode === "auto") this.showRealm(msg.realm);
      else if (this.prefs.realmMode === "ask" && realmChanged) this.askRealm = msg.realm;
    } else {
      this.askRealm = null;
      this.realmPinned = false;
    }
    this.updatePlayer();
    if (this.layout.rotateWithHeading && msg.heading != null && msg.realm === this.shownRealm) this.bridge.setBearingDeg(msg.heading);
  }

  private playerLatLng(): LatLng | null {
    if (!this.pos || this.pos.realm !== this.shownRealm) return null;
    return [this.pos.z, this.pos.x];
  }

  private isStale() {
    return !this.wsOpen || this.engine.status !== "attached" || performance.now() - this.freshAt > STALE_MS;
  }

  private updatePlayer() {
    const ll = this.playerLatLng();
    this.bridge.setPlayer(ll && {
      lat: ll[0], lng: ll[1], heading: this.pos?.heading ?? null, stale: this.isStale(), size: this.layout.markerSize,
    });
  }

  private tick() {
    this.updatePlayer();
    this.render();
  }

  // ── actions ────────────────────────────────────────────────────

  private setFollow(on: boolean) {
    if (on) this.toPlayerRealm();
    this.layout.follow = on;
    this.saveLayout();
    this.bridge.setFollow(on);
    this.render();
  }

  /** Show the realm the player is in (follow and recenter go to the player). */
  private toPlayerRealm() {
    this.realmPinned = false;
    if (this.pos && this.pos.realm !== this.shownRealm) this.showRealm(this.pos.realm);
  }

  /** Centre the map on the player once; follow / free explore stays as it is. */
  private recenter() {
    if (!this.pos) { this.notify("No live position yet"); return; }
    this.toPlayerRealm();
    const ll = this.playerLatLng();
    if (ll) this.bridge.panTo(ll);
  }

  private async keepAwake() {
    const nav = navigator as Navigator & { wakeLock?: { request(type: "screen"): Promise<unknown> } };
    if (!window.isSecureContext || !nav.wakeLock) return false;
    try { await nav.wakeLock.request("screen"); return true; } catch { return false; }
  }

  // ── markers ────────────────────────────────────────────────────

  private async loadMarkers() {
    try {
      const [data, progress] = await Promise.all([this.api.markers(), this.api.progress()]);
      this.markerData = data;
      this.markerIndex = new Map(data.markers.map((m) => [`${m.set}:${m.id}`, m]));
      this.offKeys = new Set(data.sets.flatMap((s) => s.categories.filter((c) => c.off).map((c) => `${s.id}:${c.id}`)));
      this.found = new Set(progress.found);
    } catch (e) {
      this.notify(`Markers not loaded: ${(e as Error).message}`);
      return;
    }
    if (this.selected && !this.markerIndex.has(this.selected)) this.selectMarker(null);
    this.updateMarkers();
  }

  private catKey(m: Marker) {
    return `${m.set}:${m.category}`;
  }

  private catHidden(key: string) {
    return this.offKeys.has(key) ? !this.layout.show.includes(key) : this.layout.hide.includes(key);
  }

  private isShown(m: Marker) {
    const key = `${m.set}:${m.id}`;
    return m.realm === this.shownRealm && !this.catHidden(this.catKey(m))
      && !(this.layout.hideFound && this.found.has(key));
  }

  private updateMarkers() {
    const list: MapMarker[] = [];
    for (const [key, m] of this.markerIndex) {
      if (this.isShown(m) || key === this.selected) {
        list.push({ key, name: m.name, category: m.category, x: m.x, z: m.z, found: this.found.has(key) });
      }
    }
    this.bridge.setMarkers(list);
    this.renderCard();
    if (this.sheetKind === "markers") this.renderSheet();
  }

  private setHidden(keys: string[], hidden: boolean) {
    const hide = new Set(this.layout.hide);
    const show = new Set(this.layout.show);
    for (const k of keys) {
      if (this.offKeys.has(k)) { if (hidden) show.delete(k); else show.add(k); }
      else if (hidden) hide.add(k); else hide.delete(k);
    }
    this.layout.hide = [...hide].sort();
    this.layout.show = [...show].sort();
    this.saveLayout();
    this.updateMarkers();
  }

  private selectMarker(key: string | null, pan = false) {
    this.selected = key;
    this.bridge.highlight(key);
    const m = key ? this.markerIndex.get(key) : null;
    if (m && pan) {
      if (this.layout.follow) this.setFollow(false);
      this.bridge.panTo([m.z, m.x], Math.max(this.bridge.getView().zoom, 5));
    }
    this.renderCard();
  }

  private async setFound(key: string, found: boolean) {
    try {
      await this.api.setFound(key, found);     // progress_changed updates every device, this one included
      if (found) this.found.add(key); else this.found.delete(key);
      this.updateMarkers();
    } catch (e) {
      this.notify(`Not saved: ${(e as Error).message}`);
    }
  }

  private async addMarker(x: number, z: number) {
    const name = prompt("Marker name", "")?.trim();
    if (!name) return;
    try {
      const m = await this.api.addMyMarker(name, this.shownRealm, x, z);
      await this.loadMarkers();
      this.selectMarker(`${m.set}:${m.id}`);
      this.notify(`Added "${name}"`);
    } catch (e) {
      this.notify(`Not added: ${(e as Error).message}`);
    }
  }

  private renderCard() {
    const m = this.selected ? this.markerIndex.get(this.selected) : null;
    this.card.hidden = !m;
    if (!m) { this.card.replaceChildren(); return; }
    const key = this.selected!;
    const set = this.markerData?.sets.find((s) => s.id === m.set);
    const cat = set?.categories.find((c) => c.id === m.category);
    const isFound = this.found.has(key);
    const dist = this.pos && this.pos.realm === m.realm ? Math.hypot(this.pos.x - m.x, this.pos.z - m.z) : null;
    this.card.replaceChildren(
      h("div", { class: "card-head" },
        h("span", { class: "dot", style: `background:${categoryColor(m.category)}` }),
        h("div", { class: "card-title" }, h("strong", { "data-testid": "card-name" }, m.name),
          h("span", { class: "muted" }, [cat?.name ?? m.category, dist != null ? `${dist < 1000 ? dist.toFixed(0) + " m" : (dist / 1000).toFixed(1) + " km"} away` : null]
            .filter(Boolean).join(" · "))),
        h("button", { type: "button", class: "tb", "aria-label": "Close", onclick: () => this.selectMarker(null) }, icon("close"))),
      ...(m.notes ? [h("p", { class: "muted" }, m.notes)] : []),
      h("div", { class: "row" },
        h("button", { type: "button", class: `btn small${isFound ? "" : " primary"}`, "data-testid": "card-found",
          onclick: () => void this.setFound(key, !isFound) }, isFound ? "Found ✓ (undo)" : "Mark found"),
        h("button", { type: "button", class: "btn small", onclick: () => this.selectMarker(key, true) }, "Show"),
        m.set === "my-markers" && h("button", { type: "button", class: "btn small danger", onclick: async () => {
          if (!confirm(`Delete "${m.name}"?`)) return;
          try { await this.api.deleteMyMarker(m.id); this.selectMarker(null); await this.loadMarkers(); }
          catch (e) { this.notify(`Not deleted: ${(e as Error).message}`); }
        } }, "Delete")),
      h("p", { class: "muted small" }, `${set?.name ?? m.set}${set ? ` · ${SOURCE_LABEL[set.source]}` : ""}`),
    );
  }

  private toggleMarkersSheet() {
    this.openSheet("markers");
    this.layout.sidebar = this.sheetKind === "markers" ? "expanded" : "collapsed";
    this.saveLayout();
  }

  private searchResults(): HTMLElement[] {
    const q = this.query.trim().toLowerCase();
    if (!q) return [];
    const hits: [string, Marker][] = [];
    for (const [key, m] of this.markerIndex) {
      if (m.realm === this.shownRealm && m.name.toLowerCase().includes(q)) hits.push([key, m]);
      if (hits.length >= SEARCH_LIMIT) break;
    }
    if (!hits.length) return [h("p", { class: "muted" }, "No marker with that name here.")];
    return hits.map(([key, m]) => h("button", { type: "button", class: "result", "data-testid": "search-result",
      onclick: () => { this.selectMarker(key, true); } },
      h("span", { class: "dot", style: `background:${categoryColor(m.category)}` }), m.name,
      this.found.has(key) ? h("span", { class: "tag" }, "found") : null));
  }

  private markersBody(): HTMLElement[] {
    const results = h("div", { class: "results", "data-testid": "search-results" }, ...this.searchResults());
    const search = h("input", { type: "search", placeholder: "Search markers", "data-testid": "marker-search", value: this.query,
      oninput: (e: Event) => { this.query = (e.target as HTMLInputElement).value; results.replaceChildren(...this.searchResults()); } });
    search.value = this.query;
    const data = this.markerData;
    if (!data || !data.sets.length) {
      return [search, h("p", { class: "muted", "data-testid": "markers-none" },
        "No markers yet. On the PC: launcher → Maps → Import from game files, or add your own below."), ...this.addSection()];
    }
    const inRealm = data.markers.filter((m) => m.realm === this.shownRealm);
    const count = new Map<string, [number, number]>();
    for (const m of inRealm) {
      const c = count.get(this.catKey(m)) ?? [0, 0];
      c[0] += 1;
      if (this.found.has(`${m.set}:${m.id}`)) c[1] += 1;
      count.set(this.catKey(m), c);
    }
    const allKeys = [...count.keys()];
    // categories of every set, gathered into the panel's groups
    const byGroup = new Map<string, { key: string; id: string; name: string }[]>();
    for (const set of data.sets) {
      for (const c of set.categories) {
        const key = `${set.id}:${c.id}`;
        if (!count.has(key)) continue;
        const group = set.id === "my-markers" ? "My markers" : c.group || set.name;
        byGroup.set(group, [...(byGroup.get(group) ?? []), { key, id: c.id, name: c.name }]);
      }
    }
    const rank = (g: string) => (g === "My markers" ? 1000 : GROUP_ORDER.includes(g) ? GROUP_ORDER.indexOf(g) : 100);
    const groupNames = [...byGroup.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
    const groups = groupNames.map((group) => this.categoryGroup(group, byGroup.get(group)!, count));
    return [
      search, results,
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn small", "data-testid": "cats-all", onclick: () => this.setHidden(allKeys, false) }, "Show all"),
        h("button", { type: "button", class: "btn small", "data-testid": "cats-none", onclick: () => this.setHidden(allKeys, true) }, "Hide all")),
      toggle("Hide found markers", this.layout.hideFound, (v) => { this.layout.hideFound = v; this.saveLayout(); this.updateMarkers(); }, "set-hide-found"),
      ...(groups.length ? groups : [h("p", { class: "muted" }, `No markers in ${REALMS[this.shownRealm].label}.`)]),
      ...this.addSection(),
    ];
  }

  /** A foldable panel section: header with all/none checkbox and counts, then its categories. */
  private categoryGroup(group: string, cats: { key: string; id: string; name: string }[], count: Map<string, [number, number]>) {
    const keys = cats.map((c) => c.key);
    const shown = keys.filter((k) => !this.catHidden(k)).length;
    const total = keys.reduce((n, k) => n + count.get(k)![0], 0);
    const done = keys.reduce((n, k) => n + count.get(k)![1], 0);
    const open = this.prefs.openGroups.includes(group);
    const groupBox = h("input", { type: "checkbox", "aria-label": `Show ${group}`, "data-testid": `group-${group}`,
      onchange: (e: Event) => this.setHidden(keys, !(e.target as HTMLInputElement).checked) });
    groupBox.checked = shown === keys.length;
    groupBox.indeterminate = shown > 0 && shown < keys.length;
    const fold = () => {
      const groups = new Set(this.prefs.openGroups);
      if (groups.has(group)) groups.delete(group); else groups.add(group);
      this.prefs.openGroups = [...groups];
      savePrefs(this.prefs);
      this.renderSheet();
    };
    const rows = open ? cats.map((c) => {
      const [n, f] = count.get(c.key)!;
      const box = h("input", { type: "checkbox", "data-testid": `cat-${c.key}`,
        onchange: (e: Event) => this.setHidden([c.key], !(e.target as HTMLInputElement).checked) });
      box.checked = !this.catHidden(c.key);
      return h("label", { class: "cat-row" }, box, h("img", { class: "cat-icon", src: iconUrl(c.id, false), alt: "" }),
        h("span", { class: "cat-name" }, c.name), h("span", { class: "muted" }, `${f}/${n}`));
    }) : [];
    return h("div", { class: `cat-group${open ? " open" : ""}`, "data-testid": "cat-group", "data-group": group },
      h("div", { class: "group-head" }, groupBox,
        h("button", { type: "button", class: "group-fold", "aria-expanded": String(open), "data-testid": `fold-${group}`, onclick: fold },
          h("span", { class: "chevron", "aria-hidden": "true" }, "›"),
          h("span", { class: "group-name" }, group),
          h("span", { class: "muted" }, `${cats.length} · ${done}/${total}`))),
      ...rows);
  }

  private addSection(): HTMLElement[] {
    const here = this.playerLatLng();
    return [
      h("h3", {}, "Add a marker"),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn small primary", "data-testid": "add-here", disabled: !here,
          onclick: () => { const ll = this.playerLatLng(); if (ll) void this.addMarker(ll[1], ll[0]); } }, "At my position"),
        h("button", { type: "button", class: "btn small", "data-testid": "add-by-tap",
          onclick: () => { this.addingByTap = true; this.closeSheet(); this.render(); } }, "Tap on the map")),
      h("p", { class: "muted" }, "Your markers and found ticks are saved on the PC and show on every device."),
    ];
  }

  // ── calibration (per map image) ────────────────────────────────

  private startCalibration() {
    const realm = this.shownRealm;
    const map = this.activeMap(realm);
    if (!map || map.fixed) return;
    if (!this.pos || this.isStale() || this.pos.realm !== realm) {
      this.notify(`Needs a live position in ${REALMS[realm].label}`);
      return;
    }
    this.calibrating = realm;
    this.closeSheet();
    this.render();
  }

  private async onMapTap(ll: LatLng, markerKey: string | null = null) {
    if (this.addingByTap) {
      this.addingByTap = false;
      this.render();
      await this.addMarker(ll[1], ll[0]);
      return;
    }
    const realm = this.calibrating;
    const map = realm && this.activeMap(realm);
    if (!realm || !map || !this.pos) {
      this.selectMarker(markerKey);
      return;
    }
    this.calibrating = null;
    this.render();
    try {
      // the tap is in game space as the map is placed now; the server stores it as an image pixel
      const px = gameToPx(map.georef, ll[1], ll[0]);
      const s = await this.api.addMapPoint(map.id, [this.pos.x, this.pos.z], px);
      this.notify(`Point ${s.calibration.length} saved${s.errorM != null ? `, error ${s.errorM.toFixed(1)} m` : ", add one more"}`);
      await this.loadMaps();
    } catch (e) {
      this.notify(`Calibration failed: ${(e as Error).message}`);
    }
    this.render();
  }

  private async mapAction(action: () => Promise<unknown>) {
    try { await action(); } catch (e) { this.notify(`Failed: ${(e as Error).message}`); }
    await this.loadMaps();
  }

  // ── profiles ───────────────────────────────────────────────────

  private async loadProfiles(applyStartup: boolean) {
    try {
      const data = await this.api.profiles();
      this.profiles = data.profiles;
      this.defaultProfileId = data.default;
    } catch (e) {
      this.notify(`Profiles not loaded: ${(e as Error).message}`);
      return;
    }
    if (applyStartup) {
      const start = this.profiles.find((p) => p.id === this.prefs.lastProfileId)
        ?? this.profiles.find((p) => p.id === this.defaultProfileId);
      if (start) this.applyProfile(start, false);
    }
    if (this.sheetKind === "profiles") this.renderSheet();
  }

  private applyProfile(p: Profile, announce = true) {
    this.layout = {
      follow: p.follow, rotateWithHeading: p.rotateWithHeading, markerSize: p.markerSize,
      toolbarSide: p.toolbarSide, theme: p.theme, sidebar: p.sidebar, hide: [...p.hide], show: [...(p.show ?? [])], hideFound: p.hideFound,
      mapOpacity: p.mapOpacity ?? 1, markerOpacity: p.markerOpacity ?? 1,
    };
    this.prefs.lastProfileId = p.id;
    this.saveLayout();
    this.applyLayoutChrome();
    this.bridge.setFollow(p.follow);
    this.bridge.setOpacity(this.layout.mapOpacity, this.layout.markerOpacity);
    this.bridge.setBearingDeg(p.rotateWithHeading && this.pos?.heading != null ? this.pos.heading : 0);
    if (p.zoom !== null) this.bridge.panTo(this.playerLatLng() ?? this.bridge.getView().center, p.zoom);
    this.updatePlayer();
    this.updateMarkers();
    if (p.sidebar === "expanded" && this.sheetKind !== "markers") { this.sheetKind = "markers"; this.renderSheet(); }
    else if (p.sidebar !== "expanded" && this.sheetKind === "markers") this.closeSheet();
    if (announce) this.notify(`Applied "${p.name}"`);
    this.render();
    if (this.sheetKind) this.renderSheet();
  }

  private currentLayoutProfile(name: string) {
    const view = this.bridge.getView();
    return { name, ...this.layout, zoom: Math.round(view.zoom * 100) / 100, types: [] };
  }

  private async profileAction(action: () => Promise<unknown>, done?: string) {
    try {
      await action();
      if (done) this.notify(done);
    } catch (e) {
      this.notify(e instanceof ApiError ? e.message : `Failed: ${(e as Error).message}`);
    }
    await this.loadProfiles(false);
  }

  private exportProfiles() {
    const data = JSON.stringify({ app: "companion-map", version: 2, profiles: this.profiles }, null, 2);
    const a = h("a", { href: URL.createObjectURL(new Blob([data], { type: "application/json" })), download: "companionmap-profiles.json" });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  private async importProfiles(file: File) {
    let list: Partial<Profile>[] = [];
    try {
      const doc = JSON.parse(await file.text()) as { profiles?: Partial<Profile>[] } | Partial<Profile>[];
      list = Array.isArray(doc) ? doc : doc.profiles ?? [];
    } catch {
      this.notify("Not a profiles JSON file");
      return;
    }
    let ok = 0;
    for (const p of list) {
      const { id: _id, createdAt: _c, updatedAt: _u, ...fields } = p;
      try { await this.api.createProfile(fields as Profile); ok++; } catch { /* skipped */ }
    }
    this.notify(`Imported ${ok} of ${list.length} profiles`);
    await this.loadProfiles(false);
  }

  // ── sheets ─────────────────────────────────────────────────────

  private openSheet(kind: SheetKind) {
    this.sheetKind = this.sheetKind === kind ? null : kind;
    this.renderSheet();
    this.render();
  }

  private closeSheet() {
    this.sheetKind = null;
    this.renderSheet();
  }

  private renderSheet() {
    const kind = this.sheetKind;
    const typing = kind === "markers" && document.activeElement?.getAttribute("data-testid") === "marker-search";
    if (typing) return;
    this.sheet.hidden = !kind;
    this.sheet.dataset.testid = kind ? `sheet-${kind}` : "";
    if (!kind) { this.sheet.replaceChildren(); return; }
    const title = kind === "profiles" ? "Layout profiles" : kind === "markers" ? "Markers" : "Settings";
    this.sheet.replaceChildren(
      h("div", { class: "sheet-head" }, h("h2", {}, title),
        h("button", { type: "button", class: "tb", "aria-label": "Close", "data-testid": "sheet-close", onclick: () => {
          if (this.sheetKind === "markers") { this.layout.sidebar = "collapsed"; this.saveLayout(); }
          this.closeSheet(); this.render();
        } }, icon("close"))),
      h("div", { class: "sheet-body" }, ...(kind === "profiles" ? this.profilesBody() : kind === "markers" ? this.markersBody() : this.settingsBody())),
    );
  }

  private profilesBody(): HTMLElement[] {
    const nameInput = h("input", { type: "text", placeholder: "Name, e.g. Ore run", "data-testid": "profile-name", maxlength: "60" });
    const save = () => {
      const name = nameInput.value.trim();
      if (!name) { nameInput.focus(); return; }
      void this.profileAction(async () => {
        const p = await this.api.createProfile(this.currentLayoutProfile(name));
        this.prefs.lastProfileId = p.id;
        savePrefs(this.prefs);
      }, `Saved "${name}"`);
    };
    const fileInput = h("input", { type: "file", accept: "application/json,.json", hidden: true,
      onchange: () => { const f = fileInput.files?.[0]; if (f) void this.importProfiles(f); fileInput.value = ""; } });

    const rows = this.profiles.map((p) => {
      const isDefault = p.id === this.defaultProfileId;
      return h("div", { class: `profile${p.id === this.prefs.lastProfileId ? " active" : ""}`, "data-testid": "profile-row", "data-id": p.id },
        h("div", { class: "name" }, h("span", {}, p.name), isDefault && h("span", { class: "tag" }, "Default")),
        h("div", { class: "row" },
          h("button", { type: "button", class: "btn small primary", "data-testid": "profile-apply", onclick: () => this.applyProfile(p) }, "Apply"),
          h("button", { type: "button", class: "btn small", onclick: () => {
            const name = prompt("Rename profile", p.name)?.trim();
            if (name) void this.profileAction(() => this.api.updateProfile(p.id, { name }));
          } }, "Rename"),
          h("button", { type: "button", class: "btn small", onclick: () => {
            const { id: _i, createdAt: _c, updatedAt: _u, ...copy } = p;
            void this.profileAction(() => this.api.createProfile({ ...copy, name: `${p.name} copy`.slice(0, 60) }));
          } }, "Duplicate"),
          h("button", { type: "button", class: "btn small", onclick: () =>
            void this.profileAction(() => this.api.setDefaultProfile(isDefault ? null : p.id)) }, isDefault ? "Unset default" : "Set default"),
          h("button", { type: "button", class: "btn small danger", onclick: () => {
            if (confirm(`Delete "${p.name}"?`)) void this.profileAction(() => this.api.deleteProfile(p.id));
          } }, "Delete")));
    });

    return [
      h("h3", {}, "Save current layout"),
      h("div", { class: "row" }, nameInput, h("button", { type: "button", class: "btn primary", "data-testid": "profile-save", onclick: save }, "Save")),
      h("p", { class: "muted" }, "Saves zoom, follow, rotation, toolbar side, marker size, theme, opacity and the marker filters. Profiles live on the PC, so every device sees them."),
      h("h3", {}, `Profiles (${this.profiles.length})`),
      ...(rows.length ? rows : [h("p", { class: "muted" }, "No profiles yet.")]),
      h("h3", {}, "Backup"),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn", onclick: () => this.exportProfiles() }, "Export JSON"),
        h("button", { type: "button", class: "btn", onclick: () => fileInput.click() }, "Import JSON"), fileInput),
    ];
  }

  private mapSection(): HTMLElement[] {
    const realm = this.shownRealm;
    const label = REALMS[realm].label;
    const map = this.activeMap(realm);
    const choices = (this.maps?.maps ?? []).filter((m) => m.realm === realm);
    const out: HTMLElement[] = [h("h3", {}, `Map · ${label}`)];
    if (!map) {
      out.push(h("p", { class: "muted", "data-testid": "map-none" },
        `No map imported for ${label}. On the PC: launcher → Maps → Import image. Until then the grid shows the live position.`));
      return out;
    }
    if (choices.length > 1) {
      out.push(h("div", { class: "field" }, h("span", {}, "Shown map"),
        segmented("Shown map", choices.map((m) => [m.id, m.name] as [string, string]), map.id,
          (id) => void this.mapAction(() => this.api.setActiveMap(realm, id)))));
    }
    out.push(h("p", { class: "muted" }, `${map.name} · ${map.image[0]} × ${map.image[1]} px · source: ${SOURCE_LABEL[map.source]}`));
    if (map.fixed) {
      out.push(h("p", { class: "muted", "data-testid": "map-fixed" }, "Placed exactly from the game's own map data: no calibration needed."));
      return out;
    }
    const n = map.calibration.length;
    out.push(h("p", { class: "muted", "data-testid": "map-cal-summary" },
      n < 2 ? `Not calibrated yet (${n} of at least 2 points; 3 or more show the error).`
        : `${n} points · error ${map.errorM!.toFixed(1)} m`));
    map.calibration.forEach((p, i) => {
      const r = map.residuals[i];
      out.push(h("div", { class: "row cal-point", "data-testid": "cal-point" },
        h("span", { class: "muted" }, `#${i + 1} x ${p.game[0].toFixed(0)}, z ${p.game[1].toFixed(0)}${r != null ? ` · off by ${r.toFixed(1)} m` : ""}`),
        h("button", { type: "button", class: "btn small danger", "aria-label": `Delete point ${i + 1}`,
          onclick: () => void this.mapAction(() => this.api.deleteMapPoint(map.id, i)) }, "Delete")));
    });
    out.push(h("div", { class: "row" },
      h("button", { type: "button", class: "btn small primary", "data-testid": "cal-add", onclick: () => this.startCalibration() }, "Add point"),
      n > 0 && h("button", { type: "button", class: "btn small danger", onclick: () => {
        if (confirm("Remove all calibration points of this map?")) void this.mapAction(() => this.api.resetMapCalibration(map.id));
      } }, "Reset")));
    out.push(h("p", { class: "muted" }, "Stand at a landmark in game, tap Add point, then tap that landmark on the map. Spread the points out."));
    return out;
  }

  private settingsBody(): HTMLElement[] {
    const set = <K extends keyof Layout>(key: K, value: Layout[K]) => {
      this.layout[key] = value;
      this.saveLayout();
      this.applyLayoutChrome();
      if (key === "rotateWithHeading") this.bridge.setBearingDeg(value && this.pos?.heading != null ? this.pos.heading : 0);
      if (key === "follow") this.setFollow(value as boolean);
      if (key === "markerSize") this.updatePlayer();
      this.renderSheet();
      this.render();
    };
    const realmMode = (v: RealmMode) => { this.prefs.realmMode = v; savePrefs(this.prefs); this.renderSheet(); };
    const opacity = (key: "mapOpacity" | "markerOpacity", v: number) => {   // live while dragging: no re-render
      this.layout[key] = v;
      this.saveLayout();
      this.bridge.setOpacity(this.layout.mapOpacity, this.layout.markerOpacity);
    };
    const secure = window.isSecureContext;
    const credits = (this.maps?.maps ?? []).map((m) =>
      h("li", {}, `${m.name} (${REALMS[m.realm].label}): ${SOURCE_LABEL[m.source]}${m.licence ? ` – ${m.licence}` : ""}`));

    return [
      h("h3", {}, "Map"),
      toggle("Follow player", this.layout.follow, (v) => set("follow", v), "set-follow"),
      toggle("Rotate map with heading", this.layout.rotateWithHeading, (v) => set("rotateWithHeading", v), "set-rotate"),
      h("div", { class: "field" }, h("span", {}, "Player marker size"),
        segmented("Marker size", [["small", "Small"], ["medium", "Medium"], ["large", "Large"]] as const, this.layout.markerSize, (v) => set("markerSize", v))),
      h("div", { class: "field" }, h("span", {}, "Switch realm when the player does"),
        segmented("Realm switching", [["auto", "Auto"], ["ask", "Ask"], ["manual", "Manual"]] as const, this.prefs.realmMode, realmMode)),
      h("h3", {}, "Opacity"),
      slider("Map", this.layout.mapOpacity, 0.2, 1, (v) => opacity("mapOpacity", v), "set-map-opacity"),
      slider("Markers", this.layout.markerOpacity, 0.2, 1, (v) => opacity("markerOpacity", v), "set-marker-opacity"),
      ...this.mapSection(),
      h("h3", {}, "Layout"),
      h("div", { class: "field" }, h("span", {}, "Toolbar"),
        segmented("Toolbar side", [["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]] as const, this.layout.toolbarSide, (v) => set("toolbarSide", v))),
      h("div", { class: "field" }, h("span", {}, "Theme"),
        segmented("Theme", [["auto", "Auto"], ["dark", "Dark"], ["light", "Light"]] as const, this.layout.theme, (v) => set("theme", v))),
      h("h3", {}, "Screen"),
      h("p", { class: "muted" }, secure ? "The screen is kept awake while this page is open."
        : "On the standard connection the screen can't be kept awake. Use the secure connection, or turn off auto-lock "
          + "in the device settings (iPad: Display & Brightness → Auto-Lock → Never)."),
      location.protocol === "https:" ? null
        : h("a", { class: "btn small", href: "/cdlm/setup", "data-testid": "https-setup" }, "Set up the secure connection (HTTPS)"),
      h("h3", {}, "About"),
      h("p", { class: "muted credit" }, "Runs entirely on your PC and network: no online map service. "
        + "Live position read from the game's memory, read-only. Map with OpenLayers (BSD-2-Clause)."),
      credits.length ? h("ul", { class: "muted credit", "data-testid": "map-credits" }, ...credits) : null,
      h("div", { class: "row" }, h("button", { type: "button", class: "btn small", onclick: () => {
        this.layout = { ...DEFAULT_LAYOUT };
        this.saveLayout();
        this.applyLayoutChrome();
        this.bridge.setFollow(this.layout.follow);
        this.bridge.setOpacity(1, 1);
        this.bridge.setBearingDeg(0);
        this.renderSheet();
        this.render();
      } }, "Reset layout")),
    ].filter((el): el is HTMLElement => !!el);
  }

  // ── render ─────────────────────────────────────────────────────

  private pillState(): [string, string] {
    if (!this.wsOpen) return ["red", "Offline – reconnecting"];
    switch (this.engine.status) {
      case "waiting_for_game": return ["amber", "Waiting for the game"];
      case "aob_not_found": return ["red", "Game version not supported yet"];
      case "error": return ["red", this.engine.message || "Engine error"];
    }
    if (!this.pos) return ["amber", this.engine.message || "Waiting for movement"];
    if (this.isStale()) return ["amber", "Game paused"];
    return ["green", `Live · ${REALMS[this.pos.realm].label}`];
  }

  private render() {
    const [state, text] = this.pillState();
    this.pill.dataset.state = state;
    this.pill.title = text;
    this.pill.firstElementChild!.textContent = text;

    const b = this.buttons;
    b.follow.setAttribute("aria-pressed", String(this.layout.follow));
    b.follow.title = this.layout.follow ? "Following the player: tap for free explore" : "Free explore: tap to follow the player";
    b.follow.querySelector(".caption")!.textContent = this.layout.follow ? "Follow" : "Free";
    b.recenter.disabled = !this.pos;
    b.profiles.setAttribute("aria-pressed", String(this.sheetKind === "profiles"));
    b.markers.setAttribute("aria-pressed", String(this.sheetKind === "markers"));
    b.settings.setAttribute("aria-pressed", String(this.sheetKind === "settings"));
    b.realm.querySelector(".badge")!.textContent = REALMS[this.shownRealm].label;

    const chips: HTMLElement[] = [];
    if (this.engine.status === "aob_not_found") {
      chips.push(h("div", { class: "chip warn", "data-testid": "chip-unsupported" },
        "The game was updated: no live position until the app is updated. Maps and markers still work."));
    }
    if (this.maps && !this.activeMap(this.shownRealm)) {
      chips.push(h("div", { class: "chip", "data-testid": "chip-no-map" },
        `No ${REALMS[this.shownRealm].label} map yet – import one in the launcher (Maps tab)`));
    }
    if (this.calibrating) {
      chips.push(h("div", { class: "chip warn", "data-testid": "chip-calibrating" },
        `Tap the spot where you stand (${REALMS[this.calibrating].label})`,
        h("button", { type: "button", onclick: () => { this.calibrating = null; this.render(); } }, "Cancel")));
    }
    if (this.addingByTap) {
      chips.push(h("div", { class: "chip warn", "data-testid": "chip-adding" }, "Tap where the new marker goes",
        h("button", { type: "button", onclick: () => { this.addingByTap = false; this.render(); } }, "Cancel")));
    }
    if (this.askRealm) {
      const realm = this.askRealm;
      chips.push(h("div", { class: "chip", "data-testid": "chip-realm" }, `Player is in ${REALMS[realm].label}`,
        h("button", { type: "button", onclick: () => this.showRealm(realm) }, "Switch")));
    }
    const key = chips.map((c) => c.textContent).join("|");
    if (this.chips.dataset.key !== key) {
      this.chips.dataset.key = key;
      this.chips.replaceChildren(...chips);
    }
  }

  private debugState() {
    return {
      wsOpen: this.wsOpen, engine: this.engine, follow: this.layout.follow, layout: this.layout,
      shownRealm: this.shownRealm, realmPinned: this.realmPinned, mapId: this.bridge.getView().mapId, pos: this.pos,
      stale: this.isStale(), calibrating: this.calibrating, profiles: this.profiles.length,
      mapsLoaded: this.maps !== null,
      markers: { total: this.markerIndex.size, shown: [...this.markerIndex.values()].filter((m) => this.isShown(m)).length,
        found: this.found.size, selected: this.selected },
    };
  }
}

void new App().start();
