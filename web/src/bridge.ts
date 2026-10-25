// Contract between the shell (main.ts) and the map implementation (local/olBridge.ts).
// Map space is game space: no projection or calibration between the engine and the map.

/** Map coordinates: [lat, lng] = [game z, game x]; screen up = +z. */
export type LatLng = [number, number];

export type MarkerSize = "small" | "medium" | "large";

export interface PlayerView {
  lat: number;
  lng: number;
  heading: number | null; // degrees clockwise from +z (map up), as sent by the engine
  stale: boolean;
  size: MarkerSize;
}

export interface MapView {
  center: LatLng;
  zoom: number;
  bearingDeg: number;
  mapId: string | null;
}

/** A tiled map image placed in game space (server: mapstore summary). */
export interface MapLayer {
  id: string;
  rev: string;
  image: [number, number];
  tileSize: number;
  maxZoom: number;
  /** [xmin, zmin, xmax, zmax] in game units. */
  bounds: [number, number, number, number];
  /** Tile URL template with {z}/{x}/{y}, PIN already applied. */
  tiles: string;
}

/** A marker to draw; the shell has already filtered by realm and category. */
export interface MapMarker {
  key: string;        // "<set>:<marker id>"
  name: string;
  category: string;   // icon id (category id inside its set)
  x: number;          // game x
  z: number;          // game z
  found: boolean;
}

export interface Bridge {
  version: 2;
  /** Show this map image, or only the coordinate grid. Keeps the view. */
  setMap(map: MapLayer | null): void;
  /** Player arrow; positions are smoothed between engine updates. */
  setPlayer(player: PlayerView | null): void;
  /** Keep the (smoothed) player in the centre. */
  setFollow(on: boolean): void;
  panTo(center: LatLng, zoom?: number): void;
  /** Zoom in (+1) or out (-1), animated, keeping the centre. */
  zoomBy(delta: number): void;
  /** Opacity of the map image and of the markers (0.2 .. 1); the player arrow stays opaque. */
  setOpacity(map: number, markers: number): void;
  getView(): MapView;
  /** Turn the map so that this heading points up (0 = north up). */
  setBearingDeg(deg: number): void;
  /** Screen pixel (CSS px, relative to the map element) of a map position. */
  project(ll: LatLng): [number, number];
  /** Called when the user drags, pinches or scrolls the map. */
  onUserPan(cb: () => void): () => void;
  /** Replace the drawn markers (clustered when zoomed out). */
  setMarkers(markers: MapMarker[]): void;
  /** Ring one marker (search result, open card), or none. */
  highlight(key: string | null): void;
  /** Called with the map position of a tap that was not a drag, and the marker under it.
   *  Tapping a cluster zooms into it and calls nothing. */
  onTap(cb: (ll: LatLng, markerKey: string | null) => void): () => void;
}

declare global {
  interface Window {
    cdlm?: Bridge;
  }
}
