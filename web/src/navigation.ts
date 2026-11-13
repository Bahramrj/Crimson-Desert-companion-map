// Where things are from the player, navigation to a target (along the roads where the map has a road grid), and a route through several markers. Functions of the App (main.ts): they take it as their first argument.
import type { App } from "./main";
import type { Marker } from "./api";
import { ARRIVE_M, COMPASS, fmtDist, LEVEL_M, OFF_WAY_M, type Spot, type Target, TOUR_MAX } from "./consts";
import { REALMS } from "./coord";
import { renderCard } from "./markerCard";
import { savePrefs } from "./prefs";
import { findPath } from "./roads";
import { orderStops, pathLength } from "./tour";

/** Distance and compass direction from the player, or null in another realm / without a position. */
export function whereIs(app: App, t: Spot): { dist: number; deg: number; text: string } | null {
  const p = app.pos;
  if (!p || p.realm !== t.realm) return null;
  const dist = Math.hypot(t.x - p.x, t.z - p.z);
  const deg = (Math.atan2(t.x - p.x, t.z - p.z) * 180 / Math.PI + 360) % 360;
  const dy = t.y == null ? 0 : t.y - p.y;
  const level = Math.abs(dy) >= LEVEL_M ? ` · ${Math.abs(dy).toFixed(0)} m ${dy > 0 ? "above" : "below"} you` : "";
  return { dist, deg, text: `${fmtDist(dist)} away · ${COMPASS[Math.round(deg / 45) % 8]}${level}` };
}

export function whereText(app: App, t: Spot) {
  return whereIs(app, t)?.text ?? (app.pos ? `in ${REALMS[t.realm].label}` : "");
}

/** Lead to a marker or a picked spot (null: stop). `inTour`: a stop of a route through several markers. */
export function navigate(app: App, target: Target | null, inTour = false) {
  if (!inTour) app.tour = null;
  if (!app.tour && app.prefs.tour) { app.prefs.tour = null; savePrefs(app.prefs); }
  app.target = target;
  app.wayAt = 0;
  findWay(app);
  renderNav(app);
  renderCard(app);
}

/** Look for the way along the roads (Pywel, with a road grid, when the player's position is known). */
export function findWay(app: App) {
  const t = app.target, p = app.pos;
  app.way = null;
  if (t && p && app.roads && app.prefs.roads && t.realm === "pywel" && p.realm === "pywel") {
    const found = findPath(app.roads, [p.x, p.z], [t.x, t.z]);
    if (found && found.points.length > 2) app.way = found.points.slice(1);     // without the player's own position
    app.wayAt = performance.now();
  }
  syncRoute(app);
}

/** As the player moves: drop the part of the way already walked; far off it, look for a new one. */
export function followWay(app: App) {
  const p = app.pos, way = app.way;
  if (!app.target || !p) return;
  if (!way) {
    if (!app.wayAt) findWay(app);                    // not searched yet: the position was missing
    return;
  }
  let near = 0, best = Infinity;
  for (let i = 0; i < Math.min(way.length, 12); i++) {
    const d = Math.hypot(way[i][0] - p.x, way[i][1] - p.z);
    if (d < best) { best = d; near = i; }
  }
  const passed = Math.min(best < 15 ? near + 1 : near, way.length - 1);     // the target itself stays
  if (passed > 0) { way.splice(0, passed); syncRoute(app); }
  if (best > OFF_WAY_M && performance.now() - app.wayAt > 2500) findWay(app);
}

export function wayLength(app: App) {
  const p = app.pos, way = app.way;
  if (!p || !way) return 0;
  let total = Math.hypot(way[0][0] - p.x, way[0][1] - p.z);
  for (let i = 1; i < way.length; i++) total += Math.hypot(way[i][0] - way[i - 1][0], way[i][1] - way[i - 1][1]);
  return total;
}

/** The route line, the stops ahead and the pin belong to one realm: show them only on that realm's map. */
export function syncRoute(app: App) {
  const t = app.target;
  const here = !!t && t.realm === app.shownRealm;
  app.bridge.setRoute(t && here ? [t.z, t.x] : null, app.way?.slice(0, -1));
  const ahead = app.tour && here ? app.tour.keys.slice(app.tour.index).map((k) => app.markerIndex.get(k)).filter((m) => !!m) : null;
  app.bridge.setTour(ahead && ahead.map((m) => [m.x, m.z] as [number, number]));
  const pin = app.point ?? (t && !t.key ? t : null);
  app.bridge.setPin(pin && pin.realm === app.shownRealm ? [pin.z, pin.x] : null);
}

export function renderNav(app: App) {
  const t = app.target;
  app.nav.hidden = !t;
  if (!t) return;
  const where = whereIs(app, t);
  if (where && where.dist < ARRIVE_M) {
    if (app.tour) { nextStop(app); return; }
    navigate(app, null);
    app.notify(`You are at ${t.name}`);
    return;
  }
  followWay(app);
  app.navNext.hidden = !app.tour;
  app.navName.textContent = app.tour ? `${app.tour.index + 1}/${app.tour.keys.length} · ${t.name}` : t.name;
  let info = where?.text ?? (app.pos ? `in ${REALMS[t.realm].label}` : "waiting for a live position");
  if (where && app.way) info = `${fmtDist(wayLength(app))} by road · ${where.text.split(" · ").slice(1).join(" · ")}`;
  app.navInfo.textContent = info;
}

export function planTour(app: App) {
  const view = app.bridge.getView();
  const [x0, z0, x1, z1] = view.extent;
  const stops: { key: string; m: Marker }[] = [];
  for (const [key, m] of app.markerIndex) {
    if (m.x >= x0 && m.x <= x1 && m.z >= z0 && m.z <= z1 && m.category !== "region" && !app.found.has(key) && app.isShown(m)) stops.push({ key, m });
  }
  if (stops.length < 2) { app.notify("Fewer than two markers left to find on screen"); return; }
  if (stops.length > TOUR_MAX) {
    app.notify(`${stops.length} markers on screen: zoom in or hide categories (a route takes up to ${TOUR_MAX})`);
    return;
  }
  const start = app.pos && app.pos.realm === app.shownRealm ? app.pos : { x: view.center[1], z: view.center[0] };
  const order = orderStops(start, stops.map((s) => s.m));
  app.tour = { keys: order.map((i) => stops[i].key), index: 0 };
  app.closeSheet();
  app.notify(`Route through ${stops.length} markers, ${fmtDist(pathLength(start, stops.map((s) => s.m), order))}`);
  goToStop(app);
  app.render();
}

/** Navigate to the current stop, skipping stops that were found or are gone; past the last one the route ends. */
export function goToStop(app: App) {
  const tour = app.tour;
  if (!tour) return;
  while (tour.index < tour.keys.length && (!app.markerIndex.has(tour.keys[tour.index]) || app.found.has(tour.keys[tour.index]))) tour.index++;
  if (tour.index >= tour.keys.length) {
    navigate(app, null);
    app.notify("Route finished");
    return;
  }
  const key = tour.keys[tour.index];
  const m = app.markerIndex.get(key)!;
  app.prefs.tour = { keys: tour.keys, index: tour.index };       // a reload goes on from this stop
  savePrefs(app.prefs);
  navigate(app, { realm: m.realm, x: m.x, z: m.z, y: m.y, key, name: m.name }, true);
}

export function nextStop(app: App) {
  if (!app.tour) return;
  app.tour.index++;
  goToStop(app);
}
