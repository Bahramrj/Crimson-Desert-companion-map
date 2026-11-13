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
  /** The part of the world on screen: [xmin, zmin, xmax, zmax] in game units (its bounding box when turned). */
  extent: [number, number, number, number];
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
  /** An own marker's colour ("#rrggbb") instead of the colour of its category. */
  color?: string;
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
  /** Called whenever the map turns (pinch, heading-up, setBearingDeg), with the heading that points up. */
  onRotate(cb: (bearingDeg: number) => void): () => void;
  /** A dashed line from the player to this spot, and an arrow at the screen edge while it is out of view.
   *  `via`: game [x, z] points the line passes on its way (a route along the roads). */
  setRoute(to: LatLng | null, via?: [number, number][]): void;
  /** The stops still ahead on a route through several markers, as game [x, z] points; null hides it. */
  setTour(points: [number, number][] | null): void;
  /** The map under the markers is dark (the Abyss, a night map, no map): names are drawn light on a dark edge. */
  setDarkLabels(on: boolean): void;
  /** Called when map tiles start loading and when the last one has arrived. */
  onLoading(cb: (busy: boolean) => void): () => void;
  /** A thin line between two spots (the measuring start and the open card's spot), or none. */
  setMeasure(line: [LatLng, LatLng] | null): void;
  /** Zoomed out, draw the markers as a heat map instead of numbered clusters. */
  setHeat(on: boolean): void;
  /** Zoom to this level, animated (the minimal view zooms with the player's speed). */
  zoomTo(zoom: number): void;
  /** Where the player has been: [game x, game z] points, null starts a new stretch. null hides it. */
  setTrail(points: ([number, number] | null)[] | null): void;
  /** Night colours for the map image (a light map only; markers and the arrow keep their colours). */
  setDark(on: boolean): void;
  /** A pin on a spot the user picked (long press), or none. */
  setPin(at: LatLng | null): void;
  /** Called with the map position of a long press (a finger held still for about half a second). */
  onLongPress(cb: (ll: LatLng) => void): () => void;
  /** Screen pixel (CSS px, relative to the map element) of a map position. */
  project(ll: LatLng): [number, number];
  /** Called when the user drags, pinches or scrolls the map. */
  onUserPan(cb: () => void): () => void;
  /** Replace the drawn markers (clustered when zoomed out). */
  setMarkers(markers: MapMarker[]): void;
  /** Redraw one marker as found / not found, without replacing the others. */
  setFound(key: string, found: boolean): void;
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
