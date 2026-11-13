// Local map on OpenLayers (bundled, no CDN). The view works in game units: OL [x, y] =
// game [x, z], so the engine position, markers and map tiles share one coordinate space.
import "ol/ol.css";
import OlMap from "ol/Map";
import ScaleLine from "ol/control/ScaleLine";
import Overlay from "ol/Overlay";
import View from "ol/View";
import Feature from "ol/Feature";
import LineString from "ol/geom/LineString";
import MultiLineString from "ol/geom/MultiLineString";
import Point from "ol/geom/Point";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import Projection from "ol/proj/Projection";
import Cluster from "ol/source/Cluster";
import VectorSource from "ol/source/Vector";
import XYZ from "ol/source/XYZ";
import CircleStyle from "ol/style/Circle";
import Fill from "ol/style/Fill";
import Icon from "ol/style/Icon";
import Stroke from "ol/style/Stroke";
import Style from "ol/style/Style";
import Text from "ol/style/Text";
import TileGrid from "ol/tilegrid/TileGrid";
import { defaults as defaultInteractions } from "ol/interaction/defaults";
import type { Bridge, LatLng, MapLayer, MapMarker, MapView, PlayerView } from "../bridge";
import { WORLD } from "../coord";
import { categoryColor, iconUrl, onIconsChanged } from "./icons";

const RAD = Math.PI / 180;
const SIZES = { small: 26, medium: 36, large: 48 } as const;
const SMOOTH_MS = 90;        // time constant of the arrow's glide between engine updates
const SNAP_M = 150;          // jumps further than this (fast travel, realm change) are not animated
const GRID_M = 1000;
const MAX_RES = 19460 / 256;  // zoom 0: the pre-2.04 world square in 256 px, so saved zoom levels keep their scale
const DEFAULT_MIN_RES = 0.4;  // m/px; a map may zoom to half its own pixel size, but not less close than this
const zoomFor = (resolution: number) => Math.log2(MAX_RES / resolution);
const CLUSTER_ABOVE = 4;     // m/px: cluster markers when zoomed out further than this (~2 000 game markers)
const CLUSTER_PX = 34;
const LABELS_BELOW = 1.6;    // m/px: show marker names when zoomed in closer than this
const REGION = "region";     // category of province names: drawn as map lettering, not as markers
const REGIONS_ABOVE = 2.5;   // m/px: province names show when zoomed out further than this

const ARROW = `<div class="ring"></div><svg viewBox="-12 -12 24 24" aria-hidden="true">
<path d="M0-11 9 9 0 4.5-9 9Z" fill="#38bdf8" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

const PIN = `<svg viewBox="0 0 24 30" aria-hidden="true"><path d="M12 1a9 9 0 0 1 9 9c0 6.5-9 19-9 19S3 16.500 3 10a9 9 0 0 1 9-9z"
 fill="#2f6fe8" stroke="#fff" stroke-width="2"/><circle cx="12" cy="10" r="3.2" fill="#fff"/></svg>`;
const EDGE = `<svg viewBox="-18 -18 36 36" aria-hidden="true"><circle r="16" fill="#2f6fe8" stroke="#fff" stroke-width="2"/>
<path d="M0-9 7 5 0 2-7 5Z" fill="#fff"/></svg>`;
const LONG_PRESS_MS = 550;
const PRESS_SLOP = 8;        // px a finger may move and still count as held
const EDGE_INSET = 30;       // px from the screen edge to the centre of the out-of-view arrow

const PROJECTION = new Projection({ code: "CDLM:GAME", units: "m", extent: [...WORLD] });

function gridLayer(): VectorLayer {
  const [xmin, zmin, xmax, zmax] = WORLD;
  const features: Feature[] = [];
  const line = (a: number[], b: number[], major: boolean) => {
    const f = new Feature(new LineString([a, b]));
    f.set("major", major);
    features.push(f);
  };
  for (let x = Math.ceil(xmin / GRID_M) * GRID_M; x <= xmax; x += GRID_M) line([x, zmin], [x, zmax], x % (5 * GRID_M) === 0);
  for (let z = Math.ceil(zmin / GRID_M) * GRID_M; z <= zmax; z += GRID_M) line([xmin, z], [xmax, z], z % (5 * GRID_M) === 0);
  const minor = new Style({ stroke: new Stroke({ color: "rgba(255,255,255,0.08)", width: 1 }) });
  const major = new Style({ stroke: new Stroke({ color: "rgba(255,255,255,0.2)", width: 1.5 }) });
  return new VectorLayer({
    source: new VectorSource({ features }),
    style: (f) => (f.get("major") ? major : minor),
    updateWhileInteracting: true,
  });
}

const iconStyles = new Map<string, Style>();
const labelStyles = new Map<string, Style>();      // per marker: a style with its name, made once, not per frame
const highlightStyle = new Style({ image: new CircleStyle({ radius: 21, stroke: new Stroke({ color: "#38bdf8", width: 4 }) }) });

let darkLabels = false;        // names light on a dark edge, for dark maps

function markerStyle(m: MapMarker, resolution: number, named = false): Style {
  const key = `${m.category}|${m.found}|${m.color ?? ""}`;
  let style = iconStyles.get(key);
  if (!style) {
    // icons always draw (and labels avoid them); labels that would overlap are left out
    style = new Style({ image: new Icon({ src: iconUrl(m.category, m.found, m.color), width: 28, height: 28, opacity: m.found ? 0.7 : 1,
      declutterMode: "obstacle" }) });
    iconStyles.set(key, style);
  }
  if (resolution >= LABELS_BELOW && !named) return style;       // `named`: the selected marker always shows its name
  const labelKey = `${m.key}|${m.found}`;
  let labelled = labelStyles.get(labelKey);
  if (!labelled) {
    labelled = new Style({
      image: style.getImage() ?? undefined,
      text: new Text({ text: m.name, offsetY: 24, font: "600 12px -apple-system, system-ui, sans-serif",
        fill: new Fill({ color: darkLabels ? "#f8fafc" : "#111827" }),
        stroke: new Stroke({ color: darkLabels ? "rgba(10,12,16,0.9)" : "rgba(255,255,255,0.9)", width: 3 }) }),
    });
    labelStyles.set(labelKey, labelled);
  }
  return labelled;
}

const regionStyles = new Map<string, Style>();

function regionStyle(m: MapMarker): Style {
  let style = regionStyles.get(m.name);
  if (!style) {
    style = new Style({
      text: new Text({ text: m.name.toUpperCase().split("").join(" "), font: "700 17px Georgia, 'Times New Roman', serif",
        fill: new Fill({ color: "rgba(127,29,29,0.85)" }), stroke: new Stroke({ color: "rgba(250,245,230,0.85)", width: 4 }) }),
    });
    regionStyles.set(m.name, style);
  }
  return style;
}

const clusterStyles = new Map<string, Style>();

/** A cluster in the colour of the kind of marker it holds most of, with their number. */
function clusterStyle(count: number, color: string): Style {
  const key = `${color}|${count}`;
  let style = clusterStyles.get(key);
  if (!style) {
    if (clusterStyles.size > 3000) clusterStyles.clear();
    style = new Style({
      image: new CircleStyle({ radius: count > 99 ? 18 : count > 9 ? 15 : 13, fill: new Fill({ color }),
        stroke: new Stroke({ color: "#fff", width: 2.5 }) }),
      text: new Text({ text: String(count), font: "700 12px -apple-system, system-ui, sans-serif", fill: new Fill({ color: "#fff" }),
        stroke: new Stroke({ color: "rgba(0,0,0,0.35)", width: 2.5 }) }),
    });
    clusterStyles.set(key, style);
  }
  return style;
}

/** The colour most of a cluster's markers have; kept on the cluster, which lives until the next grouping. */
function clusterColor(cluster: Feature, members: Feature<Point>[]): string {
  let color = cluster.get("tone") as string | undefined;
  if (!color) {
    const tally = new Map<string, number>();
    let most = 0;
    for (const member of members) {
      const m = member.get("marker") as MapMarker;
      const c = m.color || categoryColor(m.category);
      const n = (tally.get(c) ?? 0) + 1;
      tally.set(c, n);
      if (n > most) { most = n; color = c; }
    }
    cluster.set("tone", color, true);
  }
  return color ?? "#111827";
}

// OpenLayers picks the tile level by CSS pixels, so on a 2x screen every map pixel would be stretched
// over 2x2 device pixels. There the 512 px tiles are declared as 2x tiles of 256 CSS px: one map pixel
// per device pixel, as sharp as the screen (and 4x the tiles per view, which the LAN handles easily).
const HIDPI = typeof window !== "undefined" && window.devicePixelRatio >= 1.5;

function tileLayer(m: MapLayer): TileLayer<XYZ> {
  const [xmin, , xmax, zmax] = m.bounds;
  const mpp = (xmax - xmin) / m.image[0];
  const ratio = HIDPI ? 2 : 1;
  const resolutions = Array.from({ length: m.maxZoom + 1 }, (_, z) => ratio * mpp * 2 ** (m.maxZoom - z));
  const tileGrid = new TileGrid({ extent: m.bounds, origin: [xmin, zmax], resolutions, tileSize: m.tileSize / ratio });
  return new TileLayer({
    source: new XYZ({ url: m.tiles, projection: PROJECTION, tileGrid, tilePixelRatio: ratio, wrapX: false, interpolate: true }),
    extent: m.bounds,
    preload: Infinity,                    // every coarser level of the view: a blurry map, never an empty one
    className: "ol-layer map-tiles",      // its own canvas, so the dark-map filter leaves markers alone
  });
}

export function createBridge(target: HTMLElement): Bridge {
  const marker = document.createElement("div");
  marker.id = "cdlm-player";
  marker.innerHTML = ARROW;
  marker.hidden = true;
  const overlay = new Overlay({ element: marker, positioning: "center-center", stopEvent: false });
  const grid = gridLayer();
  const markerSource = new VectorSource<Feature<Point>>();
  const clusters = new Cluster({ source: markerSource, distance: CLUSTER_PX });
  let highlighted: string | null = null;
  const single = (m: MapMarker, resolution: number) => {
    const style = markerStyle(m, resolution, m.key === highlighted);
    return m.key === highlighted ? [highlightStyle, style] : style;
  };
  // Two layers over the same markers: clusters when zoomed out, every marker by itself when zoomed in.
  // Only one is in range at a time, so zooming among single markers never groups them again.
  const clusterLayer = new VectorLayer({
    source: clusters,
    zIndex: 10,
    declutter: true,
    minResolution: CLUSTER_ABOVE,
    style: (f, resolution) => {
      const members = f.get("features") as Feature<Point>[];
      return members.length > 1 ? clusterStyle(members.length, clusterColor(f as Feature, members))
        : single(members[0].get("marker") as MapMarker, resolution);
    },
  });
  const markerLayer = new VectorLayer({
    source: markerSource,
    zIndex: 10,
    declutter: true,
    maxResolution: CLUSTER_ABOVE,
    style: (f, resolution) => single(f.get("marker") as MapMarker, resolution),
  });
  // zoomed out, instead of the clusters when the user asks for it: where a kind of marker is dense
  // One faint disc per marker; where they overlap the colour builds up. (OpenLayers' own Heatmap layer
  // needs its WebGL code: 140 KB more for the device to load.)
  const heatStyle = new Style({ image: new CircleStyle({ radius: 13, fill: new Fill({ color: "rgba(234,88,12,0.13)" }) }) });
  const heatLayer = new VectorLayer({ source: markerSource, zIndex: 9, minResolution: CLUSTER_ABOVE, visible: false, style: heatStyle });
  const markerLayers = [clusterLayer, markerLayer];
  const redrawMarkers = () => markerLayers.forEach((l) => l.changed());
  onIconsChanged(() => { iconStyles.clear(); labelStyles.clear(); redrawMarkers(); });
  const regionSource = new VectorSource<Feature<Point>>();
  const regionLayer = new VectorLayer({
    source: regionSource,
    zIndex: 15,                        // above the markers; taps still reach them (only the marker layers are hit-tested)
    minResolution: REGIONS_ABOVE,
    style: (f) => regionStyle(f.get("marker") as MapMarker),
  });
  const view = new View({
    projection: PROJECTION,
    center: [(WORLD[0] + WORLD[2]) / 2, (WORLD[1] + WORLD[3]) / 2],
    maxResolution: MAX_RES,
    maxZoom: zoomFor(DEFAULT_MIN_RES),   // per map, see setMap
    zoom: 3,
    extent: [...WORLD],
    constrainOnlyCenter: true,
    smoothExtentConstraint: true,
  });
  // navigation: a dashed line from the player to the target, a pin, and an arrow at the screen edge
  const routeLine = new LineString([]);
  const routeLayer = new VectorLayer({
    source: new VectorSource({ features: [new Feature(routeLine)] }),
    zIndex: 8, visible: false, updateWhileAnimating: true, updateWhileInteracting: true,
    style: [new Style({ stroke: new Stroke({ color: "rgba(255,255,255,0.85)", width: 6 }) }),
      new Style({ stroke: new Stroke({ color: "#2f6fe8", width: 3, lineDash: [10, 8] }) })],
  });
  const trailLine = new MultiLineString([]);
  const trailLayer = new VectorLayer({
    source: new VectorSource({ features: [new Feature(trailLine)] }),
    zIndex: 7, visible: false,
    style: [new Style({ stroke: new Stroke({ color: "rgba(255,255,255,0.7)", width: 5 }) }),
      new Style({ stroke: new Stroke({ color: "rgba(234,88,12,0.9)", width: 2.5 }) })],
  });
  const measureLine = new LineString([]);
  const measureLayer = new VectorLayer({
    source: new VectorSource({ features: [new Feature(measureLine)] }),
    zIndex: 8, visible: false,
    style: [new Style({ stroke: new Stroke({ color: "rgba(255,255,255,0.9)", width: 5 }) }),
      new Style({ stroke: new Stroke({ color: "#111827", width: 2, lineDash: [4, 6] }) })],
  });
  const tourLine = new LineString([]);
  const tourLayer = new VectorLayer({
    source: new VectorSource({ features: [new Feature(tourLine)] }),
    zIndex: 8, visible: false,
    style: [new Style({ stroke: new Stroke({ color: "rgba(255,255,255,0.8)", width: 5 }) }),
      new Style({ stroke: new Stroke({ color: "#7c3aed", width: 2.5 }) })],
  });
  const pin = document.createElement("div");
  pin.id = "cdlm-pin";
  pin.innerHTML = PIN;
  const pinOverlay = new Overlay({ element: pin, positioning: "bottom-center", stopEvent: false });
  const edge = document.createElement("div");
  edge.id = "cdlm-edge";
  edge.innerHTML = EDGE;
  edge.hidden = true;
  const map = new OlMap({ target, view, controls: [new ScaleLine({ units: "metric", minWidth: 72 })], layers: [grid, trailLayer, tourLayer, measureLayer, routeLayer, heatLayer, regionLayer, clusterLayer, markerLayer], overlays: [pinOverlay, overlay],
    interactions: defaultInteractions({ pinchRotate: true, altShiftDragRotate: true }) });

  let current: { id: string; key: string; layer: TileLayer<XYZ> } | null = null;
  let mapOpacity = 1;
  let player: PlayerView | null = null;
  let shown: [number, number] | null = null;      // smoothed arrow position, game [x, z]
  let follow = false;
  let last = performance.now();
  const panListeners = new Set<() => void>();
  const tapListeners = new Set<(ll: LatLng, markerKey: string | null) => void>();
  const rotateListeners = new Set<(bearingDeg: number) => void>();
  const pressListeners = new Set<(ll: LatLng) => void>();
  const loadListeners = new Set<(busy: boolean) => void>();
  let pendingTiles = 0;
  const tilesPending = (change: number) => {
    const was = pendingTiles > 0;
    pendingTiles = Math.max(0, pendingTiles + change);
    if (was !== pendingTiles > 0) loadListeners.forEach((cb) => cb(pendingTiles > 0));
  };
  target.appendChild(edge);
  let routeTo: [number, number] | null = null;
  let routeVia: [number, number][] = [];
  let routeDrawn = "";
  let pressTimer = 0;
  let pressAt: [number, number] = [0, 0];
  let swallowClick = false;      // the click that ends a long press is not a tap
  target.addEventListener("pointerdown", (e) => {
    clearTimeout(pressTimer);
    swallowClick = false;
    if (!e.isPrimary || (e.pointerType === "mouse" && e.button !== 0)) return;
    pressAt = [e.clientX, e.clientY];
    pressTimer = window.setTimeout(() => {
      const box = target.getBoundingClientRect();
      const c = map.getCoordinateFromPixel([pressAt[0] - box.left, pressAt[1] - box.top]);
      if (!c) return;
      swallowClick = true;
      pressListeners.forEach((cb) => cb([c[1], c[0]]));
    }, LONG_PRESS_MS);
  }, true);
  target.addEventListener("pointermove", (e) => {
    if (!e.isPrimary || Math.hypot(e.clientX - pressAt[0], e.clientY - pressAt[1]) > PRESS_SLOP) clearTimeout(pressTimer);
  }, true);
  for (const type of ["pointerup", "pointercancel", "wheel"]) target.addEventListener(type, () => clearTimeout(pressTimer), true);

  /** The line follows the smoothed arrow; the edge arrow sits where the way to the target leaves the screen. */
  function drawRoute() {
    if (!routeTo) return;
    const key = shown ? `${shown[0].toFixed(2)},${shown[1].toFixed(2)},${routeTo[0]},${routeTo[1]}` : "";
    if (key !== routeDrawn) {
      routeDrawn = key;
      routeLayer.setVisible(!!shown);
      if (shown) routeLine.setCoordinates([shown, ...routeVia, routeTo]);
    }
    const px = map.getPixelFromCoordinate(routeTo);
    const size = map.getSize();
    if (!px || !size) return;
    const inside = px[0] >= 0 && px[0] <= size[0] && px[1] >= 0 && px[1] <= size[1];
    edge.hidden = inside;
    if (inside) return;
    const cx = size[0] / 2, cy = size[1] / 2, dx = px[0] - cx, dy = px[1] - cy;
    const t = Math.min((cx - EDGE_INSET) / Math.max(Math.abs(dx), 1e-6), (cy - EDGE_INSET) / Math.max(Math.abs(dy), 1e-6));
    edge.style.transform = `translate(${cx + dx * t}px, ${cy + dy * t}px) rotate(${Math.atan2(dx, -dy)}rad)`;
  }
  view.on("change:rotation", () => rotateListeners.forEach((cb) => cb(-view.getRotation() / RAD)));

  // zoomTo eases the zoom here, frame by frame: a view animation would be cancelled by the follow, which
  // re-centres and turns the map with every position
  let zoomGoal: number | null = null;
  const userPan = () => { zoomGoal = null; panListeners.forEach((cb) => cb()); };
  map.on("pointerdrag", userPan);
  target.addEventListener("wheel", userPan, { passive: true });
  map.on("click", (e) => {
    if (swallowClick) { swallowClick = false; return; }
    const [x, z] = e.coordinate;
    const hit = map.forEachFeatureAtPixel(e.pixel, (f) => f as Feature,
      { layerFilter: (l) => l === clusterLayer || l === markerLayer, hitTolerance: 8 });
    const members = (hit?.get("features") as Feature<Point>[] | undefined) ?? (hit ? [hit as Feature<Point>] : []);
    if (members.length > 1) {                         // a cluster: zoom in on it instead
      view.animate({ center: (hit!.getGeometry() as Point).getCoordinates(), zoom: (view.getZoom() ?? 0) + 2, duration: 250 });
      return;
    }
    const key = members.length ? (members[0].get("marker") as MapMarker).key : null;
    tapListeners.forEach((cb) => cb([z, x], key));
  });

  function frame(now: number) {
    requestAnimationFrame(frame);
    const dt = Math.min(now - last, 500);
    last = now;
    if (zoomGoal !== null) {
      const zoom = view.getZoom() ?? zoomGoal;
      const next = zoom + (zoomGoal - zoom) * (1 - Math.exp(-dt / 220));
      if (Math.abs(zoomGoal - next) < 0.004) { view.setZoom(zoomGoal); zoomGoal = null; } else view.setZoom(next);
    }
    if (!player) { marker.hidden = true; shown = null; drawRoute(); return; }
    const target: [number, number] = [player.lng, player.lat];
    if (!shown || Math.hypot(target[0] - shown[0], target[1] - shown[1]) > SNAP_M) shown = [...target];
    else {
      const k = 1 - Math.exp(-dt / SMOOTH_MS);
      shown = [shown[0] + (target[0] - shown[0]) * k, shown[1] + (target[1] - shown[1]) * k];
    }
    overlay.setPosition(shown);
    if (follow) {
      const c = view.getCenter();
      if (!c || Math.abs(c[0] - shown[0]) > 0.01 || Math.abs(c[1] - shown[1]) > 0.01) view.setCenter(shown);
    }
    const size = SIZES[player.size];
    marker.hidden = false;
    marker.style.width = marker.style.height = `${size}px`;
    // the arrow's screen angle: heading plus whatever the view rotation does to it
    const rot = player.heading == null ? 0 : player.heading + view.getRotation() / RAD;
    marker.style.setProperty("--rot", `${rot}deg`);
    marker.classList.toggle("stale", player.stale);
    drawRoute();
  }
  requestAnimationFrame(frame);

  const bridge: Bridge = {
    version: 2,
    setMap(m) {
      const key = m ? `${m.tiles}|${m.bounds.join(",")}` : null;   // rev or calibration changed: new layer
      if ((current?.key ?? null) === key) return;
      if (current) map.removeLayer(current.layer);
      current = m && key ? { id: m.id, key, layer: tileLayer(m) } : null;
      tilesPending(-pendingTiles);                    // the old map's tiles no longer count
      if (current) {
        const source = current.layer.getSource();
        source?.on("tileloadstart", () => tilesPending(1));
        source?.on("tileloadend", () => tilesPending(-1));
        source?.on("tileloaderror", () => tilesPending(-1));
        current.layer.setOpacity(mapOpacity);
        map.getLayers().insertAt(0, current.layer);
      }
      grid.setVisible(!current);
      // closest zoom: half the map's own pixel size (a high-resolution map zooms further)
      const mpp = m ? (m.bounds[2] - m.bounds[0]) / m.image[0] : Infinity;
      view.setMaxZoom(zoomFor(Math.min(DEFAULT_MIN_RES, mpp / 2)));
    },
    setPlayer(p) { player = p; },
    setMarkers(list) {
      const feature = (m: MapMarker) => {
        const f = new Feature(new Point([m.x, m.z]));
        f.set("marker", m);
        f.setId(m.key);
        return f;
      };
      labelStyles.clear();
      markerSource.clear(true);
      regionSource.clear(true);
      markerSource.addFeatures(list.filter((m) => m.category !== REGION).map(feature));
      regionSource.addFeatures(list.filter((m) => m.category === REGION).map(feature));
    },
    setFound(key, found) {
      const f = markerSource.getFeatureById(key);
      if (!f) return;
      (f.get("marker") as MapMarker).found = found;      // the style reads it; no feature is replaced
      redrawMarkers();
    },
    highlight(key) {
      highlighted = key;
      redrawMarkers();
    },
    setFollow(on) {
      follow = on;
      if (on && shown) view.setCenter(shown);
    },
    panTo(center, zoom) {
      const c = [center[1], center[0]];
      if (zoom === undefined) view.animate({ center: c, duration: 200 });
      else { view.setCenter(c); view.setZoom(zoom); }
    },
    zoomBy(delta) {
      const zoom = view.getZoom() ?? 0;
      view.animate({ zoom: Math.min(view.getMaxZoom(), Math.max(view.getMinZoom(), zoom + delta)), duration: 200 });
    },
    setOpacity(mapValue, markers) {
      mapOpacity = mapValue;
      current?.layer.setOpacity(mapValue);
      grid.setOpacity(mapValue);
      markerLayers.forEach((l) => l.setOpacity(markers));
      regionLayer.setOpacity(markers);
    },
    getView(): MapView {
      const c = view.getCenter() ?? [0, 0];
      const e = view.calculateExtent(map.getSize());
      return { center: [c[1], c[0]], zoom: view.getZoom() ?? 0, bearingDeg: -view.getRotation() / RAD, mapId: current?.id ?? null,
        extent: [e[0], e[1], e[2], e[3]] };
    },
    setBearingDeg(deg) { view.setRotation(-deg * RAD); },
    project(ll) {
      map.renderSync();
      const px = map.getPixelFromCoordinate([ll[1], ll[0]]);
      return px ? [px[0], px[1]] : [NaN, NaN];
    },
    zoomTo(zoom) { zoomGoal = Math.min(view.getMaxZoom(), Math.max(view.getMinZoom(), zoom)); },
    setTrail(points) {
      trailLayer.setVisible(!!points);
      const lines: number[][][] = [[]];
      for (const p of points ?? []) {
        if (p) lines[lines.length - 1].push(p); else lines.push([]);
      }
      trailLine.setCoordinates(lines.filter((line) => line.length > 1));
    },
    setDark(on) { target.classList.toggle("dark-map", on); },
    setDarkLabels(on) {
      if (on === darkLabels) return;
      darkLabels = on;
      labelStyles.clear();
      redrawMarkers();
    },
    onLoading(cb) { loadListeners.add(cb); return () => loadListeners.delete(cb); },
    setMeasure(line) {
      measureLayer.setVisible(!!line);
      measureLine.setCoordinates(line ? line.map((ll) => [ll[1], ll[0]]) : []);
    },
    setTour(points) {
      tourLayer.setVisible(!!points && points.length > 1);
      tourLine.setCoordinates(points ?? []);
    },
    setHeat(on) {
      heatLayer.setVisible(on);
      clusterLayer.setVisible(!on);
    },
    setRoute(to, via) {
      routeVia = via ?? [];
      routeTo = to ? [to[1], to[0]] : null;
      routeDrawn = "";
      if (!routeTo) { routeLayer.setVisible(false); edge.hidden = true; }
    },
    setPin(at) { pinOverlay.setPosition(at ? [at[1], at[0]] : undefined); },
    onLongPress(cb) { pressListeners.add(cb); return () => pressListeners.delete(cb); },
    onRotate(cb) { rotateListeners.add(cb); return () => rotateListeners.delete(cb); },
    onUserPan(cb) { panListeners.add(cb); return () => panListeners.delete(cb); },
    onTap(cb) { tapListeners.add(cb); return () => tapListeners.delete(cb); },
  };
  window.cdlm = bridge;
  return bridge;
}
