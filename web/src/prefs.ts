// Per-device preferences in localStorage. Storage can be missing or throw (private
// mode, cleared data): everything falls back to defaults.
import type { Profile } from "./api";

export type RealmMode = "auto" | "ask" | "manual";

export type Layout = Pick<Profile, "follow" | "rotateWithHeading" | "markerSize" | "toolbarSide" | "theme" | "sidebar" | "hide" | "show" | "hideFound"
  | "mapOpacity" | "markerOpacity">;

export interface Prefs {
  layout: Layout;
  realmMode: RealmMode;
  lastProfileId: string | null;
  /** Marker panel groups the user unfolded (per device). */
  openGroups: string[];
}

const KEY = "cdlm.prefs";

export const DEFAULT_LAYOUT: Layout = {
  follow: true, rotateWithHeading: false, markerSize: "medium", toolbarSide: "bottom", theme: "auto", sidebar: "collapsed",
  hide: [], show: [], hideFound: false, mapOpacity: 1, markerOpacity: 1,
};

export function loadPrefs(): Prefs {
  let raw: Partial<Prefs> = {};
  try { raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>; } catch { /* defaults */ }
  return {
    layout: { ...DEFAULT_LAYOUT, ...(raw.layout ?? {}) },
    realmMode: raw.realmMode ?? "auto",
    lastProfileId: raw.lastProfileId ?? null,
    openGroups: Array.isArray(raw.openGroups) ? raw.openGroups : [],
  };
}

export function savePrefs(prefs: Prefs) {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* not persisted */ }
}
