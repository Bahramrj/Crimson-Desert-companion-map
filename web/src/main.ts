// Device shell (tablet, phone, browser): the local map (local/olBridge.ts) with live tracking, follow mode, realm
// switching, layout profiles and per-map calibration on top. Works fully offline.
// Its panels, the marker card, navigation and the chrome around the map are in markersPanel.ts, settingsPanel.ts,
// markerCard.ts, navigation.ts and chrome.ts: functions that take this App.
import "./styles.css";
import { Api, ApiError, type MapListing, type MapSummary, type Marker, type MarkerListing, type MarkerSet, type OwnMarker, type Profile, type Rule } from "./api";
import type { Bridge, LatLng, MapLayer, MapMarker } from "./bridge";
import { quickProfiles, sheetGrip, showCoach, wake } from "./chrome";
import { type ButtonKey, HUD_ZOOM, NARROW_LANDSCAPE, OFFLINE_MS, QUICK_PROFILES, type SheetKind, type Spot, STALE_MS, type Target, TICK_MS, TRAIL_JUMP_M, TRAIL_POINTS, TRAIL_STEP_M } from "./consts";
import { gameToPx, type Realm, REALMS } from "./coord";
import { Live, type PositionMsg, type ServerMsg } from "./live";
import { onIconsChanged, setGameIcons, setIconSheet } from "./local/icons";
import { createBridge } from "./local/olBridge";
import { renderCard } from "./markerCard";
import { markersBody, renderNearby } from "./markersPanel";
import { findWay, goToStop, navigate, nextStop, renderNav, syncRoute, whereText } from "./navigation";
import { type Layout, loadPrefs, savePrefs } from "./prefs";
import { loadRoads, type RoadGrid } from "./roads";
import { profilesBody, settingsBody } from "./settingsPanel";
import { h, icon, type IconName } from "./ui";

export class App {
  api = new Api(new URLSearchParams(location.search).get("k") ?? "");
  prefs = loadPrefs();
  layout: Layout = { ...this.prefs.layout };

  mapEl = h("div", { id: "map", "data-testid": "map" });
  pill = h("div", { id: "pill", "data-testid": "pill", role: "status" }, h("span", {}, "Connecting…"));
  chips = h("div", { id: "chips" });
  toolbar = h("nav", { id: "toolbar", "aria-label": "Menu" });
  controls = h("div", { id: "controls", "aria-label": "Map controls", role: "group" });
  sheet = h("section", { id: "sheet", hidden: true, role: "dialog", "aria-modal": "false", "aria-labelledby": "sheet-title" });
  toast = h("div", { id: "toast", hidden: true, role: "status", "aria-live": "polite", "aria-atomic": "true" });
  card = h("section", { id: "card", hidden: true, "data-testid": "marker-card", role: "region", "aria-label": "Marker details" });
  loading = h("div", { id: "loading", role: "status", "data-testid": "loading" },
    h("span", { class: "spinner", "aria-hidden": "true" }), h("span", {}, "Loading the map…"));
  sheetOpener: HTMLElement | null = null;   // focus goes back here when the sheet closes
  buttons = {} as Record<ButtonKey, HTMLButtonElement>;

  bridge!: Bridge;
  wsOpen = false;
  everOpen = false;                 // the first connection: start() is already loading maps and markers
  renderKey = "";
  engine = { status: "waiting_for_game", message: "" };
  pos: PositionMsg | null = null;
  lastTs: number | null | undefined = undefined;
  freshAt = 0;
  shownRealm: Realm = "pywel";
  askRealm: Realm | null = null;
  /** The user picked the realm the player is not in: no automatic switching until the player
   *  changes realm, or follow / recenter takes the view back to the player. */
  realmPinned = false;
  maps: MapListing | null = null;
  calibrating: Realm | null = null;
  markerData: MarkerListing | null = null;
  markerIndex = new Map<string, Marker>();
  found = new Set<string>();
  until = new Map<string, number>();   // found ticks that end by themselves: key -> epoch seconds
  rules: Record<string, Rule> = {};    // per category "<set>:<category>"
  rulesOpen = false;                   // the rules part of the marker card is unfolded
  offKeys = new Set<string>();     // categories hidden until switched on
  trail: Partial<Record<Realm, ([number, number] | null)[]>> = {};
  hud = false;                        // the minimal view: only the map, the arrow and the status
  hudBefore = { follow: true, rotate: false };
  hudZoom = 0;
  hudWant = 0;
  hudWantTicks = 0;
  speed = 0;                          // m/s, smoothed
  lastPosAt = 0;
  hudExit = h("button", { type: "button", id: "hud-exit", "data-testid": "hud-exit", onclick: () => this.setHud(false) }, "Show controls");
  /** An own marker being made (id null) or changed; its form is in the card. */
  editing: (OwnMarker & { id: string | null }) | null = null;
  roads: RoadGrid | null = null;       // the Pywel road grid, when the game import made one
  roadsUrl = "";
  way: [number, number][] | null = null;   // the road route ahead: game [x, z], ending at the target
  wayAt = 0;                           // when it was last searched (0: not yet for this target)
  tour: { keys: string[]; index: number } | null = null;   // a route through several markers
  navNext = h("button", { type: "button", "data-testid": "nav-next", hidden: true, onclick: () => nextStop(this) }, "Next");
  measureFrom: Spot | null = null;    // "Measure from here": cards show the distance to this spot
  closedAt = performance.now();        // when the connection to the PC was lost (or the page started)
  loadbar = h("div", { id: "loadbar", hidden: true, "aria-hidden": "true" });
  loadTimer = 0;
  idleTimer = 0;
  quick = h("div", { id: "quick", hidden: true, role: "menu", "aria-label": "Apply a profile", "data-testid": "quick" });
  coach = h("div", { id: "coach", hidden: true, role: "dialog", "aria-label": "Tips", "data-testid": "coach" });
  coachStep = -1;
  point: Spot | null = null;          // a spot picked with a long press (its card is open)
  target: Target | null = null;       // where "Navigate" leads
  nav = h("div", { id: "nav", hidden: true, "data-testid": "nav", role: "status" });
  navName = h("strong", {});
  navInfo = h("span", { "data-testid": "nav-info" });
  cardWhere: HTMLElement | null = null;   // the live "600 m away · east" line of the open card
  cardSpot: Spot | null = null;
  nearbyEl: HTMLElement | null = null;
  nearbyKeys = "";
  ticks = 0;
  loadedSets = new Set<string>();  // sets whose markers are in markerIndex (lazy ones join when switched on)
  loadingSets = new Set<string>();
  selected: string | null = null;
  addingByTap = false;
  query = "";
  profiles: Profile[] = [];
  defaultProfileId: string | null = null;
  sheetKind: SheetKind | null = null;
  toastTimer = 0;
  live = new Live(this.api.withPin(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/cdlm/ws`), {
    open: () => {
      this.wsOpen = true;
      // after a reconnect the PC may have new maps or markers; on the first connection start() loads them
      if (this.everOpen) { void this.loadMaps(); void this.loadMarkers(); void this.loadRules(); }
      this.everOpen = true;
      this.render();
    },
    close: () => { this.wsOpen = false; this.closedAt = performance.now(); this.render(); },
    message: (msg) => this.onMessage(msg),
  });

  async start() {
    this.buildToolbar();
    this.nav.append(h("div", { class: "nav-text" }, this.navName, this.navInfo), this.navNext,
      h("button", { type: "button", "data-testid": "nav-stop", onclick: () => navigate(this, null) }, "Stop"));
    document.body.append(this.loadbar, this.quick, this.coach);
    document.body.append(this.mapEl, this.pill, this.nav, this.hudExit, this.chips, this.controls, this.toolbar, this.sheet, this.card, this.toast, this.loading);
    document.addEventListener("keydown", (e) => this.onKey(e));
    sheetGrip(this);
    this.bridge = createBridge(this.mapEl);
    setGameIcons(this.layout.gameIcons);
    onIconsChanged(() => {            // panel rows and the marker card show icons too
      if (this.sheetKind === "markers") this.renderSheet();
      this.render();
    });
    this.bridge.onUserPan(() => { if (this.layout.follow) this.setFollow(false); });
    this.bridge.onTap((ll, key) => void this.onMapTap(ll, key));
    this.bridge.onRotate((deg) => this.showCompass(deg));
    this.bridge.onLongPress((ll) => this.pickPoint(ll));
    this.bridge.onLoading((busy) => {                 // a thin bar while map tiles arrive; not for a blink
      clearTimeout(this.loadTimer);
      if (busy) this.loadTimer = window.setTimeout(() => { this.loadbar.hidden = false; }, 250);
      else this.loadbar.hidden = true;
    });
    for (const type of ["pointerdown", "keydown", "wheel"]) document.addEventListener(type, () => wake(this), true);
    document.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse") wake(this); }, true);
    document.addEventListener("pointerdown", (e) => {     // a tap elsewhere closes the quick profile list
      if (!this.quick.hidden && !this.quick.contains(e.target as Node)) this.quick.hidden = true;
    }, true);
    matchMedia(NARROW_LANDSCAPE).addEventListener("change", () => this.applyLayoutChrome());
    quickProfiles(this, this.buttons.profiles);
    this.applyLayoutChrome();
    this.bridge.setFollow(this.layout.follow);
    this.bridge.setOpacity(this.layout.mapOpacity, this.layout.markerOpacity);
    this.syncMapLook();
    this.live.start();
    setInterval(() => this.tick(), TICK_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") { this.live.kick(); void this.keepAwake(); }
    });
    void this.keepAwake();
    await Promise.all([this.loadMaps(), this.loadProfiles(true), this.loadMarkers(), this.loadRules()]);
    if (!this.prefs.coached) showCoach(this, 0);
    if (this.prefs.tour) {                 // a route was in progress before the page was reloaded
      this.tour = { keys: [...this.prefs.tour.keys], index: this.prefs.tour.index };
      goToStop(this);
    }
    (window as unknown as { cdlmShell: unknown }).cdlmShell = { state: () => this.debugState() };
  }

  // ── toolbar and chrome ─────────────────────────────────────────

  buildToolbar() {
    const make = (key: ButtonKey, name: IconName, label: string, onclick: () => void, prefix = "tb", caption = "") => {
      const b = h("button", { type: "button", class: `tb ${key}`, "aria-label": label, title: label, "data-testid": `${prefix}-${key}`, onclick },
        icon(name), caption && h("span", { class: "caption", "aria-hidden": "true" }, caption));
      this.buttons[key] = b;
      return b;
    };
    this.toolbar.append(
      make("realm", "realm", "Switch realm", () => this.showRealm(this.shownRealm === "pywel" ? "abyss" : "pywel", true)),
      make("markers", "filters", "Markers", () => this.toggleMarkersSheet(), "tb", "Markers"),
      make("profiles", "profiles", "Layout profiles", () => this.openSheet("profiles"), "tb", "Profiles"),
      make("settings", "settings", "Settings", () => this.openSheet("settings"), "tb", "Settings"),
    );
    this.buttons.realm.append(h("span", { class: "badge", "data-testid": "realm-badge" }));
    // on the map: follow / free explore, then zoom in, recenter, zoom out
    const follow = make("follow", "follow", "Follow player", () => this.setFollow(!this.layout.follow), "ctl");
    follow.append(icon("free"), h("span", { class: "caption", "data-testid": "follow-mode" }));
    const compass = make("compass", "compass", "Turn the map north up", () => this.northUp(), "ctl");
    compass.hidden = true;                 // shows only while the map is turned
    this.controls.append(follow, compass,
      h("div", { class: "zoom" },
        make("zoomIn", "plus", "Zoom in", () => this.bridge.zoomBy(1), "ctl"),
        make("recenter", "recenter", "Show my position", () => this.recenter(), "ctl"),
        make("zoomOut", "minus", "Zoom out", () => this.bridge.zoomBy(-1), "ctl")));
  }

  /** The compass needle points to the map's north; the button is only there while the map is turned. */
  showCompass(bearingDeg: number) {
    const b = this.buttons.compass;
    b.hidden = Math.abs(bearingDeg) < 0.5;
    b.style.setProperty("--north", `${-bearingDeg}deg`);
  }

  northUp() {
    if (this.layout.rotateWithHeading) {   // heading-up would turn it straight back
      this.layout.rotateWithHeading = false;
      this.saveLayout();
      if (this.sheetKind === "settings") this.renderSheet();
      this.notify("Rotate with heading is off");
    }
    this.bridge.setBearingDeg(0);
  }

  // ── buttons that step back while following ─────────────────────

  // ── the quick profile list: hold the Profiles button ───────────

  // ── first-run tips ─────────────────────────────────────────────

  applyLayoutChrome() {
    const root = document.documentElement;
    if (this.layout.theme === "auto") delete root.dataset.theme; else root.dataset.theme = this.layout.theme;
    // a phone on its side has no height for a bottom bar: the toolbar goes to the left there
    const narrow = this.layout.toolbarSide === "bottom" && matchMedia(NARROW_LANDSCAPE).matches;
    document.body.dataset.toolbar = narrow ? "left" : this.layout.toolbarSide;
    const dark = this.layout.theme === "dark" || (this.layout.theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0b0d11" : "#eef0f4");
  }

  onKey(e: KeyboardEvent) {
    if (e.key !== "Escape" || e.defaultPrevented || document.querySelector("dialog[open]")) return;     // a question handles its own Escape
    if (this.sheetKind) {
      if (this.sheetKind === "markers") { this.layout.sidebar = "collapsed"; this.saveLayout(); }
      this.closeSheet();
    } else if (!this.quick.hidden) this.quick.hidden = true;
    else if (this.coachStep >= 0) showCoach(this, -1);
    else if (this.selected || this.point || this.editing) this.selectMarker(null);
    else if (this.hud) this.setHud(false);
    else if (this.target) navigate(this, null);
    else if (this.calibrating || this.addingByTap) { this.calibrating = null; this.addingByTap = false; }
    else return;
    e.preventDefault();
    this.render();
  }

  saveLayout() {
    this.prefs.layout = { ...this.layout };
    savePrefs(this.prefs);
  }

  notify(text: string) {
    this.toast.textContent = text;
    this.toast.hidden = false;
    clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => { this.toast.hidden = true; }, 3500);
  }

  // ── maps ───────────────────────────────────────────────────────

  activeMap(realm: Realm): MapSummary | null {
    const id = this.maps?.active[realm];
    return this.maps?.maps.find((m) => m.id === id) ?? null;
  }

  /** The realm's game map in night colours, when this device asks for them and the import made one. */
  nightMap(realm: Realm): MapSummary | null {
    return this.prefs.darkMap ? this.maps?.maps.find((m) => m.realm === realm && m.style === "night") ?? null : null;
  }

  layerFor(realm: Realm): MapLayer | null {
    const m = this.nightMap(realm) ?? this.activeMap(realm);
    return m && { id: m.id, rev: m.rev, image: m.image, tileSize: m.tileSize, maxZoom: m.maxZoom,
      bounds: m.bounds, tiles: this.api.withPin(m.tiles) };
  }

  async loadMaps() {
    try {
      this.maps = await this.api.maps();
    } catch (e) {
      this.notify(`Maps not loaded: ${(e as Error).message}`);
      return;
    } finally {
      this.loading.hidden = true;
    }
    this.syncMapLook();
    if (this.sheetKind === "settings") this.renderSheet();
    this.render();
    void this.loadRoadGrid();
  }

  async loadRoadGrid() {
    const map = this.activeMap("pywel");
    const url = map?.roads ? this.api.withPin(map.roads) : "";
    if (url === this.roadsUrl) return;
    this.roadsUrl = url;
    this.roads = null;
    if (!map || !url) return;
    try {
      const grid = await loadRoads(url, map.bounds);
      if (this.roadsUrl !== url) return;
      this.roads = grid;
      findWay(this);
    } catch { /* no grid: routes are straight lines */ }
  }

  showRealm(realm: Realm, manual = false) {
    this.askRealm = null;
    if (manual) this.realmPinned = !!this.pos && this.pos.realm !== realm;
    if (realm === this.shownRealm) return;
    this.shownRealm = realm;
    this.calibrating = null;
    this.bridge.setMap(this.layerFor(realm));
    this.selectMarker(null);
    syncRoute(this);
    this.syncMapLook();
    this.updateMarkers();
    if (manual && this.pos && this.pos.realm !== realm) this.setFollow(false);
    this.updatePlayer();
    if (this.sheetKind === "settings") this.renderSheet();
    this.render();
  }

  // ── live data ──────────────────────────────────────────────────

  onMessage(msg: ServerMsg) {
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
        if (msg.found && msg.until) this.until.set(msg.key, msg.until); else this.until.delete(msg.key);
        if (msg.auto && msg.found && !this.found.has(msg.key)) this.notify(`Found: ${msg.name || "a marker"} (ticked as you got there)`);
        this.applyFound(msg.key, msg.found);
        break;
      case "trail":
        this.trail = msg.points;
        this.syncMapLook();
        break;
      case "rules_changed":
        void this.loadRules();
        break;
    }
    this.render();
  }

  onPosition(msg: PositionMsg) {
    if (msg.ts !== this.lastTs) {
      this.lastTs = msg.ts;
      this.freshAt = performance.now();
    }
    const realmChanged = this.pos?.realm !== msg.realm;
    this.trackMovement(msg);
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

  /** Speed (for the minimal view's zoom) and the trail, from one position to the next. */
  trackMovement(msg: PositionMsg) {
    const now = performance.now();
    const dt = (now - this.lastPosAt) / 1000;
    if (this.pos && this.pos.realm === msg.realm && dt > 0.02 && dt < 5) {
      const v = Math.min(60, Math.hypot(msg.x - this.pos.x, msg.z - this.pos.z) / dt);
      this.speed += (v - this.speed) * Math.min(1, dt / 2);
    }
    this.lastPosAt = now;
    const points = this.trail[msg.realm] ??= [];
    let last: [number, number] | null = null;
    for (let i = points.length - 1; i >= 0 && !last; i--) last = points[i];
    const step = last ? Math.hypot(msg.x - last[0], msg.z - last[1]) : Infinity;
    if (step < TRAIL_STEP_M) return;
    if (last && step > TRAIL_JUMP_M && points[points.length - 1]) points.push(null);
    points.push([msg.x, msg.z]);
    if (points.length > TRAIL_POINTS) points.splice(0, points.length - TRAIL_POINTS);
    if (this.prefs.trail && msg.realm === this.shownRealm) this.bridge.setTrail(points);
  }

  /** What depends on the shown realm and on per-device switches: the trail and the night colours. */
  syncMapLook() {
    this.bridge.setTrail(this.prefs.trail ? this.trail[this.shownRealm] ?? [] : null);
    // night colours: the night map of the import if there is one, else a colour filter (the Abyss map is dark already)
    if (this.maps) this.bridge.setMap(this.layerFor(this.shownRealm));
    this.bridge.setDark(this.prefs.darkMap && this.shownRealm === "pywel" && !this.nightMap("pywel"));
    this.bridge.setHeat(this.prefs.heat);
    this.bridge.setDarkLabels(this.shownRealm === "abyss" || (!!this.maps && !this.activeMap(this.shownRealm))
      || (this.prefs.darkMap && this.shownRealm === "pywel"));
  }

  /** The minimal view: follow, heading up, zoom by speed, no buttons. Leaving it puts things back. */
  setHud(on: boolean) {
    if (on === this.hud) return;
    this.hud = on;
    document.body.toggleAttribute("data-hud", on);
    if (on) {
      this.hudBefore = { follow: this.layout.follow, rotate: this.layout.rotateWithHeading };
      this.closeSheet();
      this.selectMarker(null);
      this.layout.rotateWithHeading = true;
      this.hudZoom = this.hudWant = 0;
      this.setFollow(true);
      if (this.pos?.heading != null) this.bridge.setBearingDeg(this.pos.heading);
    } else {
      this.layout.rotateWithHeading = this.hudBefore.rotate;
      if (!this.hudBefore.rotate) this.bridge.setBearingDeg(0);
      this.setFollow(this.hudBefore.follow);
    }
    this.render();
  }

  hudTick() {
    const want = HUD_ZOOM.find(([below]) => this.speed < below)![1];
    this.hudWantTicks = want === this.hudWant ? this.hudWantTicks + 1 : 0;
    this.hudWant = want;
    // a new pace has to last two seconds, so a short stop does not pump the zoom (the first one applies at once)
    if (want !== this.hudZoom && (this.hudZoom === 0 || this.hudWantTicks >= 8)) {
      this.hudZoom = want;
      this.bridge.zoomTo(want);
    }
  }

  playerLatLng(): LatLng | null {
    if (!this.pos || this.pos.realm !== this.shownRealm) return null;
    return [this.pos.z, this.pos.x];
  }

  isStale() {
    return !this.wsOpen || this.engine.status !== "attached" || performance.now() - this.freshAt > STALE_MS;
  }

  updatePlayer() {
    const ll = this.playerLatLng();
    this.bridge.setPlayer(ll && {
      lat: ll[0], lng: ll[1], heading: this.pos?.heading ?? null, stale: this.isStale(), size: this.layout.markerSize,
    });
  }

  tick() {
    this.updatePlayer();
    this.render();
    renderNav(this);
    if (this.hud) this.hudTick();
    if (this.cardWhere && this.cardSpot) this.cardWhere.textContent = whereText(this, this.cardSpot);
    if (++this.ticks % 4 === 0 && this.sheetKind === "markers") renderNearby(this);
  }

  // ── where things are from the player: distance, direction, height ──

  // ── navigation and picked spots ────────────────────────────────

  // ── a route through the markers on screen ──────────────────────

  pickPoint(ll: LatLng) {
    if (this.calibrating || this.addingByTap) return;
    this.selected = null;
    this.bridge.highlight(null);
    this.point = { realm: this.shownRealm, x: ll[1], z: ll[0] };
    syncRoute(this);
    renderCard(this);
  }

  async copyText(text: string) {
    try {
      if (window.isSecureContext && navigator.clipboard) await navigator.clipboard.writeText(text);
      else {                                  // plain HTTP on the LAN: no clipboard API
        const area = h("textarea", { class: "sr-only", readonly: true });
        area.value = text;
        document.body.append(area);
        area.select();
        const ok = document.execCommand("copy");
        area.remove();
        if (!ok) throw new Error("copy refused");
      }
      this.notify(`Copied: ${text}`);
    } catch {
      this.notify(text);                      // at least show it
    }
  }

  // ── actions ────────────────────────────────────────────────────

  setFollow(on: boolean) {
    if (on) this.toPlayerRealm();
    this.layout.follow = on;
    this.saveLayout();
    this.bridge.setFollow(on);
    this.render();
  }

  /** Show the realm the player is in (follow and recenter go to the player). */
  toPlayerRealm() {
    this.realmPinned = false;
    if (this.pos && this.pos.realm !== this.shownRealm) this.showRealm(this.pos.realm);
  }

  /** Centre the map on the player once; follow / free explore stays as it is. */
  recenter() {
    if (!this.pos) { this.notify("No live position yet"); return; }
    this.toPlayerRealm();
    const ll = this.playerLatLng();
    if (ll) this.bridge.panTo(ll);
  }

  async keepAwake() {
    const nav = navigator as Navigator & { wakeLock?: { request(type: "screen"): Promise<unknown> } };
    if (!window.isSecureContext || !nav.wakeLock) return false;
    try { await nav.wakeLock.request("screen"); return true; } catch { return false; }
  }

  // ── markers ────────────────────────────────────────────────────

  async loadMarkers() {
    try {
      const [data, progress] = await Promise.all([this.api.markers(), this.api.progress()]);
      const offKeys = new Set(data.sets.flatMap((s) => s.categories.filter((c) => c.off).map((c) => `${s.id}:${c.id}`)));
      // Sets that start switched off (ore, plants, animals: most of the markers) are not in the list;
      // fetch the ones in use: already loaded here, or with a category switched on.
      const inUse = data.sets.filter((s) => s.lazy && (this.loadedSets.has(s.id) || this.setInUse(s, offKeys)));
      const extra = await Promise.all(inUse.map((s) => this.api.markerSet(s.id)));
      this.markerData = data;
      setIconSheet(data.icons, (path) => this.api.withPin(path));
      this.markerIndex = new Map([...data.markers, ...extra.flatMap((e) => e.markers)].map((m) => [`${m.set}:${m.id}`, m]));
      this.loadedSets = new Set([...data.sets.filter((s) => !s.lazy).map((s) => s.id), ...extra.map((e) => e.id)]);
      this.offKeys = offKeys;
      this.found = new Set(progress.found);
      this.until = new Map(Object.entries(progress.until ?? {}));
    } catch (e) {
      this.notify(`Markers not loaded: ${(e as Error).message}`);
      return;
    }
    if (this.selected && !this.markerIndex.has(this.selected)) this.selectMarker(null);
    this.updateMarkers();
  }

  async loadRules() {
    try {
      this.rules = (await this.api.rules()).categories;
    } catch { return; }                        // an older PC app: no rules
    renderCard(this);
  }

  async setRule(category: string, patch: Rule) {
    try {
      const { rule } = await this.api.setRule(category, patch);
      if (Object.keys(rule).length) this.rules[category] = rule; else delete this.rules[category];
    } catch (e) {
      this.notify(`Not saved: ${(e as Error).message}`);
    }
    renderCard(this);
  }

  catKey(m: Marker) {
    return `${m.set}:${m.category}`;
  }

  catHidden(key: string, offKeys = this.offKeys) {
    return offKeys.has(key) ? !this.layout.show.includes(key) : this.layout.hide.includes(key);
  }

  setInUse(set: MarkerSet, offKeys = this.offKeys) {
    return set.categories.some((c) => !this.catHidden(`${set.id}:${c.id}`, offKeys));
  }

  /** Fetch the lazy sets that are switched on but not loaded yet (`all`: every lazy set, for the search).
   *  Resolves to true when markers were added. */
  async ensureSets(all = false): Promise<boolean> {
    const data = this.markerData;
    const want = (data?.sets ?? []).filter((s) => s.lazy && !this.loadedSets.has(s.id) && !this.loadingSets.has(s.id)
      && (all || this.setInUse(s)));
    if (!want.length) return false;
    want.forEach((s) => this.loadingSets.add(s.id));
    try {
      const got = await Promise.all(want.map((s) => this.api.markerSet(s.id)));
      if (this.markerData !== data) return false;          // the list was reloaded meanwhile, with what it needs
      for (const set of got) {
        for (const m of set.markers) this.markerIndex.set(`${m.set}:${m.id}`, m);
        this.loadedSets.add(set.id);
      }
    } catch (e) {
      this.notify(`Markers not loaded: ${(e as Error).message}`);
      return false;
    } finally {
      want.forEach((s) => this.loadingSets.delete(s.id));
    }
    this.updateMarkers();
    return true;
  }

  isShown(m: Marker) {
    const key = `${m.set}:${m.id}`;
    return m.realm === this.shownRealm && !this.catHidden(this.catKey(m))
      && !(this.layout.hideFound && this.found.has(key));
  }

  updateMarkers() {
    const list: MapMarker[] = [];
    for (const [key, m] of this.markerIndex) {
      if (this.isShown(m) || key === this.selected) {
        list.push({ key, name: m.name, category: m.category, x: m.x, z: m.z, found: this.found.has(key), color: m.color });
      }
    }
    this.bridge.setMarkers(list);
    renderCard(this);
    if (this.sheetKind === "markers") this.renderSheet();
    void this.ensureSets();                 // a category of a set that is not loaded yet was switched on
  }

  /** One marker found / not found (from this device or another one): redraw only that marker. */
  applyFound(key: string, found: boolean) {
    if (this.found.has(key) === found) return;
    if (found) this.found.add(key); else this.found.delete(key);
    if (found && this.tour && this.target?.key === key) nextStop(this);        // this stop of the route is done
    if (this.layout.hideFound) { this.updateMarkers(); return; }     // it leaves or joins the map
    this.bridge.setFound(key, found);
    renderCard(this);
    if (this.sheetKind === "markers") this.renderSheet();
  }

  setHidden(keys: string[], hidden: boolean) {
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

  selectMarker(key: string | null, pan = false) {
    this.selected = key;
    this.editing = null;
    this.point = null;
    syncRoute(this);
    this.bridge.highlight(key);
    const m = key ? this.markerIndex.get(key) : null;
    if (m && pan) {
      if (this.layout.follow) this.setFollow(false);
      this.bridge.panTo([m.z, m.x], Math.max(this.bridge.getView().zoom, 5));
    }
    renderCard(this);
  }

  async setFound(key: string, found: boolean) {
    try {
      const m = this.markerIndex.get(key);
      const done = await this.api.setFound(key, found, m && this.catKey(m));     // progress_changed tells every device
      if (found && done.until) this.until.set(key, done.until); else this.until.delete(key);
      this.applyFound(key, found);
      renderCard(this);
    } catch (e) {
      this.notify(`Not saved: ${(e as Error).message}`);
    }
  }

  /** Start a new own marker at this spot: its form opens in the card. */
  addMarker(x: number, z: number) {
    this.selectMarker(null);
    this.editing = { id: null, realm: this.shownRealm, x, z, name: "", notes: "", category: "mine", color: "" };
    renderCard(this, true);
    this.card.querySelector<HTMLInputElement>('[data-testid="edit-name"]')?.focus();
  }

  async saveEditing() {
    const e = this.editing;
    if (!e) return;
    const { id, ...fields } = e;
    fields.name = fields.name.trim();
    if (!fields.name) { this.card.querySelector<HTMLInputElement>('[data-testid="edit-name"]')?.focus(); return; }
    try {
      const m = id ? await this.api.updateMyMarker(id, fields) : await this.api.addMyMarker(fields);
      this.editing = null;
      await this.loadMarkers();
      this.selectMarker(`${m.set}:${m.id}`);
      this.notify(id ? `Saved "${m.name}"` : `Added "${m.name}"`);
    } catch (err) {
      this.notify(`Not saved: ${(err as Error).message}`);
    }
  }

  // ── nearest markers (in the marker panel) ──────────────────────

  toggleMarkersSheet() {
    this.openSheet("markers");
    this.layout.sidebar = this.sheetKind === "markers" ? "expanded" : "collapsed";
    this.saveLayout();
  }

  // ── calibration (per map image) ────────────────────────────────

  startCalibration() {
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

  async onMapTap(ll: LatLng, markerKey: string | null = null) {
    if (this.addingByTap) {
      this.addingByTap = false;
      this.render();
      if (this.editing) {                       // "Pick on the map" in the form: the marker moves there
        Object.assign(this.editing, { realm: this.shownRealm, x: ll[1], z: ll[0] });
        renderCard(this, true);
      } else this.addMarker(ll[1], ll[0]);
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

  async mapAction(action: () => Promise<unknown>) {
    try { await action(); } catch (e) { this.notify(`Failed: ${(e as Error).message}`); }
    await this.loadMaps();
  }

  // ── profiles ───────────────────────────────────────────────────

  async loadProfiles(applyStartup: boolean) {
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

  applyProfile(p: Profile, announce = true) {
    this.layout = {
      follow: p.follow, rotateWithHeading: p.rotateWithHeading, markerSize: p.markerSize,
      toolbarSide: p.toolbarSide, theme: p.theme, sidebar: p.sidebar, hide: [...p.hide], show: [...(p.show ?? [])], hideFound: p.hideFound,
      mapOpacity: p.mapOpacity ?? 1, markerOpacity: p.markerOpacity ?? 1, gameIcons: p.gameIcons ?? true,
    };
    this.prefs.lastProfileId = p.id;
    this.prefs.recentProfiles = [p.id, ...this.prefs.recentProfiles.filter((id) => id !== p.id)].slice(0, QUICK_PROFILES);
    this.saveLayout();
    this.applyLayoutChrome();
    this.bridge.setFollow(p.follow);
    this.bridge.setOpacity(this.layout.mapOpacity, this.layout.markerOpacity);
    setGameIcons(this.layout.gameIcons);
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

  currentLayoutProfile(name: string) {
    const view = this.bridge.getView();
    return { name, ...this.layout, zoom: Math.round(view.zoom * 100) / 100, types: [] };
  }

  async profileAction(action: () => Promise<unknown>, done?: string) {
    try {
      await action();
      if (done) this.notify(done);
    } catch (e) {
      this.notify(e instanceof ApiError ? e.message : `Failed: ${(e as Error).message}`);
    }
    await this.loadProfiles(false);
  }

  exportProfiles() {
    const data = JSON.stringify({ app: "companion-map", version: 2, profiles: this.profiles }, null, 2);
    const a = h("a", { href: URL.createObjectURL(new Blob([data], { type: "application/json" })), download: "companionmap-profiles.json" });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async restoreBackup(file: File) {
    try {
      const { added } = await this.api.restoreBackup(JSON.parse(await file.text()));
      this.notify(`Restored: ${added.found} found ticks, ${added.myMarkers} markers, ${added.profiles} profiles, ${added.rules} rules`);
    } catch (e) {
      this.notify(e instanceof ApiError ? `Not restored: ${e.message}` : "Not a backup file");
    }
  }

  async importProfiles(file: File) {
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

  openSheet(kind: SheetKind) {
    const opening = this.sheetKind !== kind;
    if (opening && !this.sheetKind) this.sheetOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.sheetKind = opening ? kind : null;
    this.renderSheet();
    this.render();
    if (opening) this.sheet.querySelector<HTMLElement>("#sheet-title")?.focus({ preventScroll: true });
    else this.returnFocus();
  }

  closeSheet() {
    const hadFocus = this.sheet.contains(document.activeElement);
    this.sheetKind = null;
    this.renderSheet();
    if (hadFocus) this.returnFocus();
  }

  returnFocus() {
    const back = this.sheetOpener;
    this.sheetOpener = null;
    if (back && back.isConnected) back.focus({ preventScroll: true });
  }

  renderSheet() {
    const kind = this.sheetKind;
    const typing = kind === "markers" && document.activeElement?.getAttribute("data-testid") === "marker-search";
    if (typing) return;
    // the same sheet again (a category ticked, a setting changed): keep where the list was scrolled to
    const same = !!kind && this.sheet.dataset.testid === `sheet-${kind}`;
    const scrolled = same ? this.sheet.querySelector<HTMLElement>(".sheet-body")?.scrollTop ?? 0 : 0;
    this.sheet.dataset.testid = kind ? `sheet-${kind}` : "";
    this.sheet.dataset.stop = this.prefs.sheetStop;
    if (!kind) {                             // it slides away, then it is gone
      const gone = () => { if (!this.sheetKind) { this.sheet.hidden = true; this.sheet.classList.remove("closing"); this.sheet.replaceChildren(); } };
      if (this.sheet.hidden || matchMedia("(prefers-reduced-motion: reduce)").matches) gone();
      else { this.sheet.classList.add("closing"); window.setTimeout(gone, 170); }
      return;
    }
    this.sheet.classList.remove("closing");
    this.sheet.hidden = false;
    // a re-render (live updates) replaces every element: keep the keyboard focus on the same control
    const focused = this.sheet.contains(document.activeElement) ? document.activeElement as HTMLElement : null;
    const again = focused?.id ? `#${CSS.escape(focused.id)}`
      : focused?.dataset.testid ? `[data-testid="${CSS.escape(focused.dataset.testid)}"]` : "#sheet-title";
    const title = kind === "profiles" ? "Layout profiles" : kind === "markers" ? "Markers" : "Settings";
    this.sheet.replaceChildren(
      h("button", { type: "button", class: "sheet-grip", "data-testid": "sheet-grip", "aria-label": "Make the panel taller or shorter" }),
      h("div", { class: "sheet-head" }, h("h2", { id: "sheet-title", tabindex: "-1" }, title),
        h("button", { type: "button", class: "tb", "aria-label": `Close ${title.toLowerCase()}`, title: "Close", "data-testid": "sheet-close", onclick: () => {
          if (this.sheetKind === "markers") { this.layout.sidebar = "collapsed"; this.saveLayout(); }
          this.closeSheet(); this.render();
        } }, icon("close"))),
      h("div", { class: "sheet-body" }, ...(kind === "profiles" ? profilesBody(this) : kind === "markers" ? markersBody(this) : settingsBody(this))),
    );
    if (scrolled) this.sheet.querySelector<HTMLElement>(".sheet-body")!.scrollTop = scrolled;
    if (focused) (this.sheet.querySelector<HTMLElement>(again) ?? this.sheet.querySelector<HTMLElement>("#sheet-title"))?.focus({ preventScroll: true });
  }

  // ── render ─────────────────────────────────────────────────────

  pillState(): [string, string] {
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

  render() {
    const [state, text] = this.pillState();
    // called on every live message (30 a second): touch the page only when something it shows changed
    const offline = !this.wsOpen && performance.now() - this.closedAt > OFFLINE_MS;
    const now = [state, text, offline, this.layout.follow, !!this.pos, this.sheetKind, this.shownRealm, this.engine.status,
      !!this.maps && !this.activeMap(this.shownRealm), this.calibrating, this.addingByTap, this.askRealm].join("|");
    if (now === this.renderKey) return;
    this.renderKey = now;
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

    document.body.toggleAttribute("data-offline", offline);          // the map goes grey: what it shows may be old
    const chips: HTMLElement[] = [];
    if (offline) {
      chips.push(h("div", { class: "chip bad", "data-testid": "chip-offline" },
        "The PC is not reachable. Is Companion Map running there, and is this device on the same Wi-Fi?",
        h("button", { type: "button", "data-testid": "offline-retry", onclick: () => { this.live.kick(); void this.loadMaps(); } }, "Try again")));
    }
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
      chips.push(h("div", { class: "chip warn", "data-testid": "chip-adding" }, "Tap where the marker goes",
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

  debugState() {
    return {
      wsOpen: this.wsOpen, engine: this.engine, follow: this.layout.follow, layout: this.layout,
      shownRealm: this.shownRealm, realmPinned: this.realmPinned, mapId: this.bridge.getView().mapId, pos: this.pos,
      stale: this.isStale(), calibrating: this.calibrating, profiles: this.profiles.length,
      target: this.target, point: this.point, roads: !!this.roads, way: this.way?.length ?? 0,
      tour: this.tour && { index: this.tour.index, keys: this.tour.keys }, hud: this.hud, speed: this.speed,
      trail: Object.fromEntries(Object.entries(this.trail).map(([realm, points]) => [realm, points.length])),
      mapsLoaded: this.maps !== null,
      markers: { total: this.markerIndex.size, shown: [...this.markerIndex.values()].filter((m) => this.isShown(m)).length,
        found: this.found.size, selected: this.selected },
    };
  }
}

void new App().start();
