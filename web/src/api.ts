// REST client for /cdlm/api (server/app.py). The PIN, if any, comes from ?k= in the shell URL.
import type { Georef, Realm } from "./coord";
import type { MarkerSize } from "./bridge";

export interface Profile {
  id: string;
  name: string;
  types: string[];
  hide: string[];
  /** Categories that are off by default (`off`) and switched on. */
  show: string[];
  zoom: number | null;
  follow: boolean;
  rotateWithHeading: boolean;
  hideFound: boolean;
  sidebar: "collapsed" | "expanded";
  toolbarSide: "bottom" | "left" | "right";
  markerSize: MarkerSize;
  theme: "auto" | "dark" | "light";
  mapOpacity: number;      // 0.2 .. 1
  markerOpacity: number;
  /** Marker icons from the game files (when imported), or our own simple ones. */
  gameIcons: boolean;
  createdAt?: number;
  updatedAt?: number;
}

export type ProfileInput = Omit<Profile, "id" | "createdAt" | "updatedAt">;

export interface CalPoint {
  game: [number, number]; // [x, z]
  px: [number, number];   // image [u, v]
}

/** mapstore.store.summary() */
export interface MapSummary {
  id: string;
  name: string;
  realm: Realm;
  source: "A" | "B" | "C";
  licence: string;
  image: [number, number];
  tileSize: number;
  maxZoom: number;
  rev: string;
  georef: Georef;
  fixed: boolean;
  calibration: CalPoint[];
  gameVersion: string | null;
  bounds: [number, number, number, number];
  tiles: string;
  /** "night": a second look of the realm's game map; a device shows it when "Night colours" is on. */
  style?: string | null;
  /** The road grid of a game-made Pywel map (web/src/roads.ts), if the import made one. */
  roads?: string | null;
  residuals: number[];
  errorM: number | null;
}

export interface MapListing {
  maps: MapSummary[];
  active: Record<Realm, string | null>;
}

/** `off`: hidden until switched on in the panel (big game sets such as ore and plants). */
export interface MarkerCategory { id: string; name: string; group?: string; off?: boolean }

export interface MarkerSet {
  id: string;
  name: string;
  source: "A" | "B" | "C";
  licence: string;
  gameVersion: string | null;
  categories: MarkerCategory[];
  count: number;
  /** All categories start off: `markers` leaves this set out, markerSet() fetches it when one is switched on. */
  lazy?: boolean;
  /** Per realm and category: [markers, found]. Lets the panel count a set that is not loaded. */
  counts?: Partial<Record<Realm, Record<string, [number, number]>>>;
}

export interface Marker {
  id: string;
  set: string;
  category: string;
  name: string;
  realm: Realm;
  x: number;
  z: number;
  y?: number;
  notes?: string;
  /** Pywel markers from the game files: the province they lie in. */
  province?: string;
  /** Own markers: a colour instead of the colour of their kind. */
  color?: string;
}

/** The game's own icons, cut from the install at import: a sprite sheet and a cell per category. */
export interface IconSheet { rev: string; url: string; cells: Record<string, [number, number, number, number]> }

/** What the user sets on an own marker; `category` is one of the kinds in mapstore/markers.py MINE_TYPES. */
export interface OwnMarker { name: string; realm: Realm; x: number; z: number; notes: string; category: string; color: string }

/** Per category: tick its markers when the player gets there; a tick ends by itself after this many hours. */
export interface Rule { auto?: boolean; respawnHours?: number }

export interface MarkerListing { sets: MarkerSet[]; markers: Marker[]; icons?: IconSheet | null }

export interface ServerStatus {
  server: { version: string; port: number; urls: string[]; clients: number; simulated: boolean; pin: boolean };
  engine: { status: string; message: string };
  game: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export class Api {
  constructor(private pin: string) {}

  withPin(path: string): string {
    return this.pin ? `${path}${path.includes("?") ? "&" : "?"}k=${encodeURIComponent(this.pin)}` : path;
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const resp = await fetch(this.withPin(`/cdlm/api${path}`), {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (resp.status === 204) return undefined as T;
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new ApiError(resp.status, (data as { error?: string }).error ?? resp.statusText);
    return data as T;
  }

  status() { return this.req<ServerStatus>("GET", "/status"); }
  profiles() { return this.req<{ profiles: Profile[]; default: string | null }>("GET", "/profiles"); }
  createProfile(p: Partial<ProfileInput> & { name: string }) { return this.req<Profile>("POST", "/profiles", p); }
  updateProfile(id: string, p: Partial<ProfileInput>) { return this.req<Profile>("PUT", `/profiles/${encodeURIComponent(id)}`, p); }
  deleteProfile(id: string) { return this.req<void>("DELETE", `/profiles/${encodeURIComponent(id)}`); }
  setDefaultProfile(id: string | null) { return this.req<{ default: string | null }>("PUT", "/profiles/default", { id }); }
  maps() { return this.req<MapListing>("GET", "/maps"); }
  setActiveMap(realm: Realm, id: string | null) { return this.req<Record<Realm, string | null>>("PUT", "/maps/active", { realm, id }); }
  addMapPoint(id: string, game: [number, number], px: [number, number]) {
    return this.req<MapSummary>("POST", `/maps/${encodeURIComponent(id)}/calibration`, { game, px });
  }
  deleteMapPoint(id: string, index: number) {
    return this.req<MapSummary>("DELETE", `/maps/${encodeURIComponent(id)}/calibration/${index}`);
  }
  resetMapCalibration(id: string) { return this.req<MapSummary>("DELETE", `/maps/${encodeURIComponent(id)}/calibration`); }
  markers() { return this.req<MarkerListing>("GET", "/markers"); }
  markerSet(id: string) { return this.req<{ id: string; markers: Marker[] }>("GET", `/markers/sets/${encodeURIComponent(id)}`); }
  progress() { return this.req<{ found: string[]; until?: Record<string, number> }>("GET", "/progress"); }
  /** `category` ("<set>:<category>") lets the PC end the tick by itself when that category comes back. */
  setFound(key: string, found: boolean, category?: string) {
    return this.req<{ key: string; found: boolean; until?: number | null }>("POST", "/progress", { key, found, category });
  }
  rules() { return this.req<{ categories: Record<string, Rule> }>("GET", "/rules"); }
  setRule(category: string, patch: Rule) { return this.req<{ category: string; rule: Rule }>("PUT", "/rules", { category, ...patch }); }
  clearTrail() { return this.req<void>("DELETE", "/trail"); }
  backupUrl() { return this.withPin("/cdlm/api/backup"); }
  restoreBackup(doc: unknown) { return this.req<{ added: Record<"found" | "rules" | "myMarkers" | "profiles", number> }>("POST", "/backup", doc); }
  addMyMarker(m: OwnMarker) { return this.req<Marker>("POST", "/markers/mine", m); }
  updateMyMarker(id: string, m: Partial<OwnMarker>) { return this.req<Marker>("PUT", `/markers/mine/${encodeURIComponent(id)}`, m); }
  deleteMyMarker(id: string) { return this.req<void>("DELETE", `/markers/mine/${encodeURIComponent(id)}`); }
}
