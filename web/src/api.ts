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
}

export interface MarkerListing { sets: MarkerSet[]; markers: Marker[] }

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
  progress() { return this.req<{ found: string[] }>("GET", "/progress"); }
  setFound(key: string, found: boolean) { return this.req<{ key: string; found: boolean }>("POST", "/progress", { key, found }); }
  addMyMarker(name: string, realm: Realm, x: number, z: number) {
    return this.req<Marker>("POST", "/markers/mine", { name, realm, x, z });
  }
  deleteMyMarker(id: string) { return this.req<void>("DELETE", `/markers/mine/${encodeURIComponent(id)}`); }
}
