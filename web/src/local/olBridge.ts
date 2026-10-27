// Local map on OpenLayers (bundled, no CDN). The view works in game units: OL [x, y] =
// game [x, z], so the engine position, markers and map tiles share one coordinate space.
import "ol/ol.css";
import OlMap from "ol/Map";
import Overlay from "ol/Overlay";
import View from "ol/View";
import Feature from "ol/Feature";
import LineString from "ol/geom/LineString";
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
import { iconUrl } from "./icons";

const RAD = Math.PI / 180;
const SIZES = { small: 26, medium: 36, large: 48 } as const;
const SMOOTH_MS = 90;        // time constant of the arrow's glide between engine updates
const SNAP_M = 150;          // jumps further than this (fast travel, realm change) are not animated
const GRID_M = 1000;
const MAX_RES = (WORLD[2] - WORLD[0]) / 256;     // zoom 0: the whole world in 256 px
const DEFAULT_MIN_RES = 0.4;  // m/px; a map may zoom to half its own pixel size, but not less close than this
const zoomFor = (resolution: number) => Math.log2(MAX_RES / resolution);
const CLUSTER_ABOVE = 4;     // m/px: cluster markers when zoomed out further than this (~2 000 game markers)
const CLUSTER_PX = 34;
const LABELS_BELOW = 1.6;    // m/px: show marker names when zoomed in closer than this
const REGION = "region";     // category of province names: drawn as map lettering, not as markers
const REGIONS_ABOVE = 2.5;   // m/px: province names show when zoomed out further than this

const ARROW = `<div class="ring"></div><svg viewBox="-12 -12 24 24" aria-hidden="true">
<path d="M0-11 9 9 0 4.5-9 9Z" fill="#38bdf8" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

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
const highlightStyle = new Style({ image: new CircleStyle({ radius: 21, stroke: new Stroke({ color: "#38bdf8", width: 4 }) }) });

function markerStyle(m: MapMarker, resolution: number): Style {
  const key = `${m.category}|${m.found}`;
  let style = iconStyles.get(key);
  if (!style) {
    // icons always draw (and labels avoid them); labels that would overlap are left out
    style = new Style({ image: new Icon({ src: iconUrl(m.category, m.found), width: 28, height: 28, opacity: m.found ? 0.7 : 1,
      declutterMode: "obstacle" }) });
    iconStyles.set(key, style);
  }
  if (resolution >= LABELS_BELOW) return style;
  return new Style({
    image: style.getImage() ?? undefined,
    text: new Text({ text: m.name, offsetY: 24, font: "600 12px -apple-system, system-ui, sans-serif",
      fill: new Fill({ color: "#111827" }), stroke: new Stroke({ color: "rgba(255,255,255,0.9)", width: 3 }) }),
  });
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

function clusterStyle(count: number): Style {
  return new Style({
    image: new CircleStyle({ radius: count > 99 ? 17 : 14, fill: new Fill({ color: "rgba(17,24,39,0.82)" }),
      stroke: new Stroke({ color: "#fff", width: 2 }) }),
    text: new Text({ text: String(count), font: "700 12px -apple-system, system-ui, sans-serif", fill: new Fill({ color: "#fff" }) }),
  });
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
    preload: 1,
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
  const markerLayer = new VectorLayer({
    source: clusters,
    zIndex: 10,
    declutter: true,
    style: (f, resolution) => {
      const members = f.get("features") as Feature<Point>[];
      if (members.length > 1) return clusterStyle(members.length);
      const m = members[0].get("marker") as MapMarker;
      const style = markerStyle(m, resolution);
      return m.key === highlighted ? [highlightStyle, style] : style;
    },
  });
  const regionSource = new VectorSource<Feature<Point>>();
  const regionLayer = new VectorLayer({
    source: regionSource,
    zIndex: 15,                        // above the markers; taps still reach them (only markerLayer is hit-tested)
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
  const map = new OlMap({ target, view, controls: [], layers: [grid, regionLayer, markerLayer], overlays: [overlay],
    interactions: defaultInteractions({ pinchRotate: true, altShiftDragRotate: true }) });

  let current: { id: string; key: string; layer: TileLayer<XYZ> } | null = null;
  let mapOpacity = 1;
  let player: PlayerView | null = null;
  let shown: [number, number] | null = null;      // smoothed arrow position, game [x, z]
  let follow = false;
  let last = performance.now();
  const panListeners = new Set<() => void>();
  const tapListeners = new Set<(ll: LatLng, markerKey: string | null) => void>();
  const updateClustering = () => clusters.setDistance((view.getResolution() ?? 0) > CLUSTER_ABOVE ? CLUSTER_PX : 0);
  view.on("change:resolution", updateClustering);
  updateClustering();

  const userPan = () => panListeners.forEach((cb) => cb());
  map.on("pointerdrag", userPan);
  target.addEventListener("wheel", userPan, { passive: true });
  map.on("click", (e) => {
    const [x, z] = e.coordinate;
    const hit = map.forEachFeatureAtPixel(e.pixel, (f) => f as Feature, { layerFilter: (l) => l === markerLayer, hitTolerance: 8 });
    const members = (hit?.get("features") as Feature<Point>[] | undefined) ?? [];
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
    if (!player) { marker.hidden = true; shown = null; return; }
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
  }
  requestAnimationFrame(frame);

  const bridge: Bridge = {
    version: 2,
    setMap(m) {
      const key = m ? `${m.tiles}|${m.bounds.join(",")}` : null;   // rev or calibration changed: new layer
      if ((current?.key ?? null) === key) return;
      if (current) map.removeLayer(current.layer);
      current = m && key ? { id: m.id, key, layer: tileLayer(m) } : null;
      if (current) {
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
        return f;
      };
      markerSource.clear(true);
      regionSource.clear(true);
      markerSource.addFeatures(list.filter((m) => m.category !== REGION).map(feature));
      regionSource.addFeatures(list.filter((m) => m.category === REGION).map(feature));
    },
    highlight(key) {
      highlighted = key;
      markerLayer.changed();
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
      markerLayer.setOpacity(markers);
      regionLayer.setOpacity(markers);
    },
    getView(): MapView {
      const c = view.getCenter() ?? [0, 0];
      return { center: [c[1], c[0]], zoom: view.getZoom() ?? 0, bearingDeg: -view.getRotation() / RAD, mapId: current?.id ?? null };
    },
    setBearingDeg(deg) { view.setRotation(-deg * RAD); },
    project(ll) {
      map.renderSync();
      const px = map.getPixelFromCoordinate([ll[1], ll[0]]);
      return px ? [px[0], px[1]] : [NaN, NaN];
    },
    onUserPan(cb) { panListeners.add(cb); return () => panListeners.delete(cb); },
    onTap(cb) { tapListeners.add(cb); return () => tapListeners.delete(cb); },
  };
  window.cdlm = bridge;
  return bridge;
}
