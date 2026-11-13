// The Markers panel: search, the nearest markers, progress, the category groups. Functions of the App (main.ts): they take it as their first argument.
import type { App } from "./main";
import type { Marker } from "./api";
import { ARROWS, fmtDist, GROUP_ORDER, LEVEL_M, NEARBY, SEARCH_CATS, SEARCH_LIMIT } from "./consts";
import { REALMS } from "./coord";
import { iconUrl } from "./local/icons";
import { planTour, whereIs } from "./navigation";
import { savePrefs } from "./prefs";
import { h, toggle } from "./ui";

export function nearbyGroup(app: App): HTMLElement {
  const open = app.prefs.nearbyOpen;
  const list = h("div", { class: "nearby", "data-testid": "nearby" });
  app.nearbyEl = open ? list : null;
  app.nearbyKeys = "";
  if (open) renderNearby(app);
  return h("div", { class: `cat-group${open ? " open" : ""}`, "data-testid": "nearby-group" },
    h("div", { class: "group-head" },
      h("button", { type: "button", class: "group-fold", "aria-expanded": String(open), "data-testid": "fold-nearby",
        onclick: () => { app.prefs.nearbyOpen = !open; savePrefs(app.prefs); app.renderSheet(); } },
        h("span", { class: "chevron", "aria-hidden": "true" }, "›"), h("span", { class: "group-name" }, "Nearest to you"))),
    list);
}

/** The closest shown, not yet found markers. Rows are rebuilt only when the list changes, so a tap
 *  is never lost to a refresh; the distances are updated in place. */
export function renderNearby(app: App) {
  const el = app.nearbyEl;
  if (!el) return;
  const p = app.pos;
  if (!p || p.realm !== app.shownRealm) {
    if (app.nearbyKeys !== "-") el.replaceChildren(h("p", { class: "muted" }, `Shows up with a live position in ${REALMS[app.shownRealm].label}.`));
    app.nearbyKeys = "-";
    return;
  }
  const best: [number, string, Marker][] = [];
  for (const [key, m] of app.markerIndex) {
    if (m.realm !== p.realm || m.category === "region") continue;
    const d = Math.hypot(m.x - p.x, m.z - p.z);
    if (best.length === NEARBY && d >= best[NEARBY - 1][0]) continue;
    if (app.found.has(key) || app.catHidden(app.catKey(m))) continue;
    best.push([d, key, m]);
    best.sort((a, b) => a[0] - b[0]);
    if (best.length > NEARBY) best.pop();
  }
  const keys = best.map((b) => b[1]).join("|") || "none";
  if (keys !== app.nearbyKeys) {
    app.nearbyKeys = keys;
    el.replaceChildren(...(best.length ? best.map(([, key, m]) => h("button", { type: "button", class: "result", "data-testid": "nearby-row",
      onclick: () => app.selectMarker(key, true) },
      h("img", { class: "cat-icon", src: iconUrl(m.category, false, m.color), alt: "" }), h("span", { class: "result-name" }, m.name),
      h("span", { class: "muted where" })))
      : [h("p", { class: "muted" }, "Nothing left to find among the shown markers.")]));
  }
  const up = app.bridge.getView().bearingDeg;         // arrows point the way on the screen, as the map is turned
  el.querySelectorAll<HTMLElement>(".where").forEach((span, i) => {
    const w = whereIs(app, best[i][2]);
    if (!w) return;
    const dy = (best[i][2].y ?? p.y) - p.y;
    const level = Math.abs(dy) >= LEVEL_M ? (dy > 0 ? " ▲" : " ▼") : "";
    span.textContent = `${fmtDist(w.dist)} ${ARROWS[Math.round(((w.deg - up + 360) % 360) / 45) % 8]}${level}`;
  });
}

/** Show this category and hide every other one (in both realms). */
export function solo(app: App, key: string) {
  const all = (app.markerData?.sets ?? []).flatMap((s) => s.categories.map((c) => `${s.id}:${c.id}`));
  app.setHidden(all.filter((k) => k !== key), true);
  app.setHidden([key], false);
}

/** What the search box finds: first the categories with that name (tick, or show only that one), then the markers. */
export function searchResults(app: App): HTMLElement[] {
  const q = app.query.trim().toLowerCase();
  if (!q) return [];
  const cats: HTMLElement[] = [];
  for (const set of app.markerData?.sets ?? []) {
    for (const c of set.categories) {
      const n = set.counts?.[app.shownRealm]?.[c.id]?.[0] ?? 0;
      if (!n || !c.name.toLowerCase().includes(q) || cats.length >= SEARCH_CATS) continue;
      const key = `${set.id}:${c.id}`;
      const box = h("input", { type: "checkbox", "data-testid": `search-cat-${key}`,
        onchange: (e: Event) => app.setHidden([key], !(e.target as HTMLInputElement).checked) });
      box.checked = !app.catHidden(key);
      cats.push(h("label", { class: "cat-row found-cat", "data-testid": "search-cat" }, box,
        h("img", { class: "cat-icon", src: iconUrl(c.id, false), alt: "" }), h("span", { class: "cat-name" }, c.name),
        h("span", { class: "muted" }, String(n)),
        h("button", { type: "button", class: "only", "data-testid": `search-only-${key}`,
          onclick: (e: Event) => { e.preventDefault(); solo(app, key); box.checked = true; app.notify(`Only “${c.name}” is shown`); } }, "only")));
    }
  }
  const all: [number, string, Marker][] = [];              // [rank, key, marker]: names that start with it first, then the nearest
  const p = app.pos && app.pos.realm === app.shownRealm ? app.pos : null;
  for (const [key, m] of app.markerIndex) {
    if (m.realm !== app.shownRealm) continue;
    const at = m.name.toLowerCase().indexOf(q);
    if (at >= 0) all.push([(at === 0 ? 0 : 1e9) + (p ? Math.hypot(m.x - p.x, m.z - p.z) : 0), key, m]);
  }
  all.sort((a, b) => a[0] - b[0] || a[2].name.localeCompare(b[2].name));
  const hits = all.slice(0, SEARCH_LIMIT).map(([, key, m]) => [key, m] as [string, Marker]);
  const more = all.length > hits.length
    ? [h("p", { class: "muted", "data-testid": "search-more" }, `${hits.length} of ${all.length} shown: type more to narrow it down.`)] : [];
  if (!hits.length && !cats.length) return [h("p", { class: "muted empty" }, `Nothing called “${app.query.trim()}” in ${REALMS[app.shownRealm].label}.`)];
  return [...cats, ...hits.map(([key, m]) => h("button", { type: "button", class: "result", "data-testid": "search-result",
    onclick: () => { app.selectMarker(key, true); } },
    h("img", { class: "cat-icon", src: iconUrl(m.category, false, m.color), alt: "" }), h("span", { class: "result-name" }, m.name),
    app.found.has(key) ? h("span", { class: "tag" }, "found") : null)), ...more];
}

export function markersBody(app: App): HTMLElement[] {
  const results = h("div", { class: "results", "data-testid": "search-results" }, ...searchResults(app));
  const input = h("input", { type: "search", placeholder: "Search markers", "aria-label": "Search markers", "data-testid": "marker-search",
    value: app.query, enterkeyhint: "search", autocomplete: "off",
    oninput: (e: Event) => {
      app.query = (e.target as HTMLInputElement).value;
      results.replaceChildren(...searchResults(app));
      // searching also covers the sets that are switched off: fetch them on the first search
      if (app.query.trim()) void app.ensureSets(true).then((added) => { if (added && results.isConnected) results.replaceChildren(...searchResults(app)); });
    } });
  input.value = app.query;
  const search = h("div", { class: "search-bar", role: "search" }, input);
  const data = app.markerData;
  if (!data || !data.sets.length) {
    return [search, h("p", { class: "muted empty", "data-testid": "markers-none" },
      "No markers yet. On the PC: launcher → Maps → Import from game files, or add your own below."), ...addSection(app)];
  }
  const count = new Map<string, [number, number]>();
  for (const [key, m] of app.markerIndex) {
    if (m.realm !== app.shownRealm) continue;
    const c = count.get(app.catKey(m)) ?? [0, 0];
    c[0] += 1;
    if (app.found.has(key)) c[1] += 1;
    count.set(app.catKey(m), c);
  }
  for (const set of data.sets) {            // sets that are not loaded: the PC counted them
    if (app.loadedSets.has(set.id)) continue;
    for (const [cat, c] of Object.entries(set.counts?.[app.shownRealm] ?? {})) count.set(`${set.id}:${cat}`, [c[0], c[1]]);
  }
  const allKeys = [...count.keys()];
  // categories of every set, gathered into the panel's groups; the game's own sets first in each group
  const byGroup = new Map<string, { key: string; id: string; name: string }[]>();
  const sets = [...data.sets].sort((a, b) => Number(b.source === "A") - Number(a.source === "A"));
  for (const set of sets) {
    for (const c of set.categories) {
      const key = `${set.id}:${c.id}`;
      if (!count.has(key)) continue;
      const group = set.id === "my-markers" ? "My markers" : c.group || set.name;
      byGroup.set(group, [...(byGroup.get(group) ?? []), { key, id: c.id, name: c.name }]);
    }
  }
  const rank = (g: string) => (g === "My markers" ? 1000 : GROUP_ORDER.includes(g) ? GROUP_ORDER.indexOf(g) : 100);
  const groupNames = [...byGroup.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const groups = groupNames.map((group) => categoryGroup(app, group, byGroup.get(group)!, count));
  let all = 0, allFound = 0;
  for (const [n, f] of count.values()) { all += n; allFound += f; }
  const overall = h("div", { class: "progress", "data-testid": "progress-all" },
    h("span", {}, `Found ${allFound} of ${all} in ${REALMS[app.shownRealm].label}`),
    h("span", { class: "muted" }, all ? `${(100 * allFound / all).toFixed(allFound && allFound * 10 < all ? 1 : 0)} %` : ""),
    h("div", { class: "bar" }, h("i", { style: `width:${all ? 100 * allFound / all : 0}%` })));
  return [
    search, results, nearbyGroup(app),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn small", "data-testid": "cats-all", onclick: () => app.setHidden(allKeys, false) }, "Show all"),
      h("button", { type: "button", class: "btn small", "data-testid": "cats-none", onclick: () => app.setHidden(allKeys, true) }, "Hide all")),
    toggle("Hide found markers", app.layout.hideFound, (v) => { app.layout.hideFound = v; app.saveLayout(); app.updateMarkers(); }, "set-hide-found"),
    toggle("Heat map when zoomed out", app.prefs.heat, (v) => { app.prefs.heat = v; savePrefs(app.prefs); app.bridge.setHeat(v); }, "set-heat"),
    h("div", { class: "row" }, h("button", { type: "button", class: "btn small", "data-testid": "tour-plan", onclick: () => planTour(app) },
      "Route through the markers on screen")),
    overall,
    ...[provinceGroup(app)].filter((el): el is HTMLElement => !!el),
    ...(groups.length ? groups : [h("p", { class: "muted empty" }, `No markers in ${REALMS[app.shownRealm].label} yet.`)]),
    ...addSection(app),
  ];
}

/** Found progress per province, over the shown categories (Pywel markers from the game files know their province). */
export function provinceGroup(app: App): HTMLElement | null {
  const by = new Map<string, [number, number]>();
  for (const [key, m] of app.markerIndex) {
    if (!m.province || m.realm !== app.shownRealm || m.category === "region" || app.catHidden(app.catKey(m))) continue;
    const c = by.get(m.province) ?? [0, 0];
    c[0] += 1;
    if (app.found.has(key)) c[1] += 1;
    by.set(m.province, c);
  }
  if (!by.size) return null;
  const open = app.prefs.provincesOpen;
  const rows = open ? [...by].sort((a, b) => a[0].localeCompare(b[0])).map(([name, [n, f]]) =>
    h("div", { class: "prov-row", "data-testid": "province-row" }, h("span", { class: "cat-name" }, name),
      h("span", { class: "muted" }, `${f}/${n}`), h("div", { class: "bar" }, h("i", { style: `width:${100 * f / n}%` })))) : [];
  return h("div", { class: `cat-group${open ? " open" : ""}`, "data-testid": "province-group" },
    h("div", { class: "group-head" },
      h("button", { type: "button", class: "group-fold", "aria-expanded": String(open), "data-testid": "fold-provinces",
        onclick: () => { app.prefs.provincesOpen = !open; savePrefs(app.prefs); app.renderSheet(); } },
        h("span", { class: "chevron", "aria-hidden": "true" }, "›"), h("span", { class: "group-name" }, "By province"),
        h("span", { class: "count" }, "shown categories"))),
    ...rows);
}

/** A foldable panel section: header with all/none checkbox and counts, then its categories. */
export function categoryGroup(app: App, group: string, cats: { key: string; id: string; name: string }[], count: Map<string, [number, number]>) {
  const keys = cats.map((c) => c.key);
  const shown = keys.filter((k) => !app.catHidden(k)).length;
  const total = keys.reduce((n, k) => n + count.get(k)![0], 0);
  const done = keys.reduce((n, k) => n + count.get(k)![1], 0);
  const open = app.prefs.openGroups.includes(group);
  const groupBox = h("input", { type: "checkbox", "aria-label": `Show ${group}`, "data-testid": `group-${group}`,
    onchange: (e: Event) => app.setHidden(keys, !(e.target as HTMLInputElement).checked) });
  groupBox.checked = shown === keys.length;
  groupBox.indeterminate = shown > 0 && shown < keys.length;
  const fold = () => {
    const groups = new Set(app.prefs.openGroups);
    if (groups.has(group)) groups.delete(group); else groups.add(group);
    app.prefs.openGroups = [...groups];
    savePrefs(app.prefs);
    app.renderSheet();
  };
  const rows = open ? cats.map((c) => {
    const [n, f] = count.get(c.key)!;
    const box = h("input", { type: "checkbox", "data-testid": `cat-${c.key}`,
      onchange: (e: Event) => app.setHidden([c.key], !(e.target as HTMLInputElement).checked) });
    box.checked = !app.catHidden(c.key);
    return h("label", { class: "cat-row" }, box, h("img", { class: "cat-icon", src: iconUrl(c.id, false), alt: "" }),
      h("span", { class: "cat-name" }, c.name), h("span", { class: "muted", title: `${f} of ${n} found` }, `${f}/${n}`),
      h("button", { type: "button", class: "only", "data-testid": `only-${c.key}`, title: `Show only ${c.name}`,
        onclick: (e: Event) => { e.preventDefault(); solo(app, c.key); app.notify(`Only “${c.name}” is shown`); } }, "only"));
  }) : [];
  return h("div", { class: `cat-group${open ? " open" : ""}`, "data-testid": "cat-group", "data-group": group },
    h("div", { class: "group-head" }, groupBox,
      h("button", { type: "button", class: "group-fold", "aria-expanded": String(open), "data-testid": `fold-${group}`, onclick: fold },
        h("span", { class: "chevron", "aria-hidden": "true" }, "›"),
        h("span", { class: "group-name" }, group),
        h("span", { class: "count", title: `${cats.length} categories · ${done} of ${total} found`,
          "aria-label": `${cats.length} categories, ${done} of ${total} found` }, `${done}/${total}`)),
      h("div", { class: "bar" }, h("i", { style: `width:${total ? 100 * done / total : 0}%` }))),
    ...rows);
}

export function addSection(app: App): HTMLElement[] {
  const here = app.playerLatLng();
  return [
    h("h3", {}, "Add a marker"),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn small primary", "data-testid": "add-here", disabled: !here,
        onclick: () => { const ll = app.playerLatLng(); if (ll) { app.closeSheet(); app.addMarker(ll[1], ll[0]); app.render(); } } }, "At my position"),
      h("button", { type: "button", class: "btn small", "data-testid": "add-by-tap",
        onclick: () => { app.addingByTap = true; app.closeSheet(); app.render(); } }, "Tap on the map")),
    h("p", { class: "muted" }, "Your markers and found ticks are saved on the PC and show on every device."),
  ];
}
