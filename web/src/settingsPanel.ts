// The Profiles and Settings panels. Functions of the App (main.ts): they take it as their first argument.
import type { App } from "./main";
import { showCoach, wake } from "./chrome";
import { SOURCE_LABEL } from "./consts";
import { REALMS } from "./coord";
import { askConfirm, askText } from "./dialog";
import { setGameIcons } from "./local/icons";
import { findWay } from "./navigation";
import { DEFAULT_LAYOUT, type Layout, type RealmMode, savePrefs } from "./prefs";
import { h, segmented, slider, toggle } from "./ui";

export function profilesBody(app: App): HTMLElement[] {
  const nameInput = h("input", { type: "text", placeholder: "Name, e.g. Ore run", "data-testid": "profile-name", maxlength: "60" });
  const save = () => {
    const name = nameInput.value.trim();
    if (!name) { nameInput.focus(); return; }
    void app.profileAction(async () => {
      const p = await app.api.createProfile(app.currentLayoutProfile(name));
      app.prefs.lastProfileId = p.id;
      savePrefs(app.prefs);
    }, `Saved "${name}"`);
  };
  const fileInput = h("input", { type: "file", accept: "application/json,.json", hidden: true,
    onchange: () => { const f = fileInput.files?.[0]; if (f) void app.importProfiles(f); fileInput.value = ""; } });

  const rows = app.profiles.map((p) => {
    const isDefault = p.id === app.defaultProfileId;
    return h("div", { class: `profile${p.id === app.prefs.lastProfileId ? " active" : ""}`, "data-testid": "profile-row", "data-id": p.id },
      h("div", { class: "name" }, h("span", {}, p.name), isDefault && h("span", { class: "tag" }, "Default")),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn small primary", "data-testid": "profile-apply", onclick: () => app.applyProfile(p) }, "Apply"),
        h("button", { type: "button", class: "btn small", "data-testid": "profile-rename", onclick: async () => {
          const name = await askText("Rename profile", p.name, "Rename");
          if (name) void app.profileAction(() => app.api.updateProfile(p.id, { name }));
        } }, "Rename"),
        h("button", { type: "button", class: "btn small", onclick: () => {
          const { id: _i, createdAt: _c, updatedAt: _u, ...copy } = p;
          void app.profileAction(() => app.api.createProfile({ ...copy, name: `${p.name} copy`.slice(0, 60) }));
        } }, "Duplicate"),
        h("button", { type: "button", class: "btn small", onclick: () =>
          void app.profileAction(() => app.api.setDefaultProfile(isDefault ? null : p.id)) }, isDefault ? "Unset default" : "Set default"),
        h("button", { type: "button", class: "btn small danger", "data-testid": "profile-delete", onclick: async () => {
          if (await askConfirm(`Delete the profile “${p.name}”?`, "Delete", true)) void app.profileAction(() => app.api.deleteProfile(p.id));
        } }, "Delete")));
  });

  return [
    h("h3", {}, "Save current layout"),
    h("div", { class: "row" }, nameInput, h("button", { type: "button", class: "btn primary", "data-testid": "profile-save", onclick: save }, "Save")),
    h("p", { class: "muted" }, "Tip: hold the Profiles button for a quick list of your profiles."),
    h("p", { class: "muted" }, "Saves zoom, follow, rotation, toolbar side, marker size, theme, opacity and the marker filters. Profiles live on the PC, so every device sees them."),
    h("h3", {}, `Profiles (${app.profiles.length})`),
    ...(rows.length ? rows : [h("p", { class: "muted empty" }, "No profiles yet. Save the current layout above to make one.")]),
    h("h3", {}, "Backup"),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn", onclick: () => app.exportProfiles() }, "Export JSON"),
      h("button", { type: "button", class: "btn", onclick: () => fileInput.click() }, "Import JSON"), fileInput),
  ];
}

export function mapSection(app: App): HTMLElement[] {
  const realm = app.shownRealm;
  const label = REALMS[realm].label;
  const map = app.activeMap(realm);
  const choices = (app.maps?.maps ?? []).filter((m) => m.realm === realm && m.style !== "night");
  const out: HTMLElement[] = [h("h3", {}, `Map · ${label}`)];
  if (!map) {
    out.push(h("p", { class: "muted empty", "data-testid": "map-none" },
      `No map imported for ${label}. On the PC: launcher → Maps → Import image. Until then the grid shows the live position.`));
    return out;
  }
  if (choices.length > 1) {
    out.push(h("div", { class: "field" }, h("span", {}, "Shown map"),
      segmented("Shown map", choices.map((m) => [m.id, m.name] as [string, string]), map.id,
        (id) => void app.mapAction(() => app.api.setActiveMap(realm, id)))));
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
        onclick: () => void app.mapAction(() => app.api.deleteMapPoint(map.id, i)) }, "Delete")));
  });
  out.push(h("div", { class: "row" },
    h("button", { type: "button", class: "btn small primary", "data-testid": "cal-add", onclick: () => app.startCalibration() }, "Add point"),
    n > 0 && h("button", { type: "button", class: "btn small danger", onclick: async () => {
      if (await askConfirm("Remove all calibration points of this map?", "Remove", true)) void app.mapAction(() => app.api.resetMapCalibration(map.id));
    } }, "Reset")));
  out.push(h("p", { class: "muted" }, "Stand at a landmark in game, tap Add point, then tap that landmark on the map. Spread the points out."));
  return out;
}

export function settingsBody(app: App): HTMLElement[] {
  const set = <K extends keyof Layout>(key: K, value: Layout[K]) => {
    app.layout[key] = value;
    app.saveLayout();
    app.applyLayoutChrome();
    if (key === "rotateWithHeading") app.bridge.setBearingDeg(value && app.pos?.heading != null ? app.pos.heading : 0);
    if (key === "follow") app.setFollow(value as boolean);
    if (key === "markerSize") app.updatePlayer();
    if (key === "gameIcons") setGameIcons(value as boolean);
    app.renderSheet();
    app.render();
  };
  const realmMode = (v: RealmMode) => { app.prefs.realmMode = v; savePrefs(app.prefs); app.renderSheet(); };
  const opacity = (key: "mapOpacity" | "markerOpacity", v: number) => {   // live while dragging: no re-render
    app.layout[key] = v;
    app.saveLayout();
    app.bridge.setOpacity(app.layout.mapOpacity, app.layout.markerOpacity);
  };
  const secure = window.isSecureContext;
  const restoreInput = h("input", { type: "file", accept: "application/json,.json", hidden: true, "data-testid": "backup-file",
    onchange: () => { const f = restoreInput.files?.[0]; if (f) void app.restoreBackup(f); restoreInput.value = ""; } });
  const credits = (app.maps?.maps ?? []).map((m) =>
    h("li", {}, `${m.name} (${REALMS[m.realm].label}): ${SOURCE_LABEL[m.source]}${m.licence ? ` – ${m.licence}` : ""}`));

  const device = (key: "trail" | "darkMap", v: boolean) => { app.prefs[key] = v; savePrefs(app.prefs); app.syncMapLook(); app.renderSheet(); };
  return [
    h("h3", {}, "Map"),
    h("button", { type: "button", class: "btn primary", "data-testid": "hud-enter", onclick: () => app.setHud(true) }, "Minimal view"),
    h("p", { class: "muted" }, "Only the map: follows you, your heading points up, zooms out when you ride or sail. "
      + "“Show controls” brings everything back."),
    toggle("Follow player", app.layout.follow, (v) => set("follow", v), "set-follow"),
    toggle("Rotate map with heading", app.layout.rotateWithHeading, (v) => set("rotateWithHeading", v), "set-rotate"),
    h("div", { class: "field" }, h("span", {}, "Player marker size"),
      segmented("Marker size", [["small", "Small"], ["medium", "Medium"], ["large", "Large"]] as const, app.layout.markerSize, (v) => set("markerSize", v))),
    h("div", { class: "field" }, h("span", {}, "Switch realm when the player does"),
      segmented("Realm switching", [["auto", "Auto"], ["ask", "Ask"], ["manual", "Manual"]] as const, app.prefs.realmMode, realmMode)),
    toggle("Show where I have been", app.prefs.trail, (v) => device("trail", v), "set-trail"),
    app.prefs.trail ? h("div", { class: "row" }, h("button", { type: "button", class: "btn small", "data-testid": "trail-clear",
      onclick: () => void app.api.clearTrail().catch((e) => app.notify(`Not cleared: ${(e as Error).message}`)) }, "Clear the trail")) : null,
    toggle("Navigate along roads", app.prefs.roads, (v) => { app.prefs.roads = v; savePrefs(app.prefs); findWay(app); app.renderSheet(); }, "set-roads"),
    toggle("Night colours for the Pywel map", app.prefs.darkMap, (v) => device("darkMap", v), "set-dark-map"),
    h("h3", {}, "Opacity"),
    slider("Map", app.layout.mapOpacity, 0.2, 1, (v) => opacity("mapOpacity", v), "set-map-opacity"),
    slider("Markers", app.layout.markerOpacity, 0.2, 1, (v) => opacity("markerOpacity", v), "set-marker-opacity"),
    h("h3", {}, "Markers"),
    toggle("Game icons", app.layout.gameIcons, (v) => set("gameIcons", v), "set-game-icons"),
    h("p", { class: "muted" }, "The game's own map icons, taken from your game files by Import from game files. "
      + "Off: simple icons."),
    ...mapSection(app),
    h("h3", {}, "Layout"),
    toggle("Hide the buttons while following", app.prefs.autoHide, (v) => { app.prefs.autoHide = v; savePrefs(app.prefs); wake(app); }, "set-autohide"),
    h("div", { class: "field" }, h("span", {}, "Toolbar"),
      segmented("Toolbar side", [["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]] as const, app.layout.toolbarSide, (v) => set("toolbarSide", v))),
    h("div", { class: "field" }, h("span", {}, "Theme"),
      segmented("Theme", [["auto", "Auto"], ["dark", "Dark"], ["light", "Light"]] as const, app.layout.theme, (v) => set("theme", v))),
    h("h3", {}, "Screen"),
    h("p", { class: "muted" }, secure ? "The screen is kept awake while this page is open."
      : "On the standard connection the screen can't be kept awake. Use the secure connection, or turn off auto-lock "
        + "in the device settings (iPad: Display & Brightness → Auto-Lock → Never)."),
    location.protocol === "https:" ? null
      : h("a", { class: "btn small", href: "/cdlm/setup", "data-testid": "https-setup" }, "Set up the secure connection (HTTPS)"),
    h("div", { class: "row" }, h("button", { type: "button", class: "btn small", "data-testid": "coach-again",
      onclick: () => { app.closeSheet(); app.render(); showCoach(app, 0); } }, "Show the tips again")),
    h("h3", {}, "Backup"),
    h("div", { class: "row" },
      h("a", { class: "btn small", href: app.api.backupUrl(), download: "", "data-testid": "backup-save" }, "Save backup file"),
      h("button", { type: "button", class: "btn small", "data-testid": "backup-restore", onclick: () => restoreInput.click() }, "Restore from file"),
      restoreInput),
    h("p", { class: "muted" }, "Found ticks, your own markers, category rules and layout profiles, as one file. "
      + "Restoring adds what is missing; nothing is removed."),
    h("h3", {}, "About"),
    h("p", { class: "muted credit" }, "Runs entirely on your PC and network: no online map service. "
      + "Live position read from the game's memory, read-only. Map with OpenLayers (BSD-2-Clause)."),
    credits.length ? h("ul", { class: "muted credit", "data-testid": "map-credits" }, ...credits) : null,
    h("div", { class: "row" }, h("button", { type: "button", class: "btn small", onclick: () => {
      app.layout = { ...DEFAULT_LAYOUT };
      app.saveLayout();
      app.applyLayoutChrome();
      app.bridge.setFollow(app.layout.follow);
      app.bridge.setOpacity(1, 1);
      setGameIcons(app.layout.gameIcons);
      app.bridge.setBearingDeg(0);
      app.renderSheet();
      app.render();
    } }, "Reset layout")),
  ].filter((el): el is HTMLElement => !!el);
}
