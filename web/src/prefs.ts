// Per-device preferences in localStorage. Storage can be missing or throw (private
// mode, cleared data): everything falls back to defaults.
import type { Profile } from "./api";

export type RealmMode = "auto" | "ask" | "manual";

export type Layout = Pick<Profile, "follow" | "rotateWithHeading" | "markerSize" | "toolbarSide" | "theme" | "sidebar" | "hide" | "show" | "hideFound"
  | "mapOpacity" | "markerOpacity" | "gameIcons">;

export interface Prefs {
  layout: Layout;
  realmMode: RealmMode;
  lastProfileId: string | null;
  /** Marker panel groups the user unfolded (per device). */
  openGroups: string[];
  /** The "Nearest to you" list in the marker panel is unfolded. */
  nearbyOpen: boolean;
  /** Draw where the player has been in this session. */
  trail: boolean;
  /** Night colours for the Pywel map. */
  darkMap: boolean;
  /** Zoomed out, a heat map instead of numbered clusters. */
  heat: boolean;
  /** "Navigate" follows the roads where the map has a road grid. */
  roads: boolean;
  /** "By province" in the marker panel is unfolded. */
  provincesOpen: boolean;
  /** How tall the panel is on a phone: a strip, half the screen, or all of it. */
  sheetStop: "peek" | "half" | "full";
  /** While following, the buttons fade away after a few seconds without a touch. */
  autoHide: boolean;
  /** The first-run tips were shown (or skipped). */
  coached: boolean;
  /** Profiles applied on this device, most recent first: the quick list on the Profiles button. */
  recentProfiles: string[];
  /** The route through several markers in progress, so a reload does not end it. */
  tour: { keys: string[]; index: number } | null;
}

const KEY = "cdlm.prefs";

export const DEFAULT_LAYOUT: Layout = {
  follow: true, rotateWithHeading: false, markerSize: "medium", toolbarSide: "bottom", theme: "auto", sidebar: "collapsed",
  hide: [], show: [], hideFound: false, mapOpacity: 1, markerOpacity: 1, gameIcons: true,
};

export function loadPrefs(): Prefs {
  let raw: Partial<Prefs> = {};
  try { raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>; } catch { /* defaults */ }
  return {
    layout: { ...DEFAULT_LAYOUT, ...(raw.layout ?? {}) },
    realmMode: raw.realmMode ?? "auto",
    lastProfileId: raw.lastProfileId ?? null,
    openGroups: Array.isArray(raw.openGroups) ? raw.openGroups : [],
    nearbyOpen: raw.nearbyOpen ?? true,
    trail: raw.trail ?? true,
    darkMap: raw.darkMap ?? false,
    heat: raw.heat ?? false,
    roads: raw.roads ?? true,
    provincesOpen: raw.provincesOpen ?? false,
    autoHide: raw.autoHide ?? true,
    coached: raw.coached ?? false,
    recentProfiles: Array.isArray(raw.recentProfiles) ? raw.recentProfiles.filter((id) => typeof id === "string") : [],
    sheetStop: raw.sheetStop === "peek" || raw.sheetStop === "full" ? raw.sheetStop : "half",
    tour: raw.tour && Array.isArray(raw.tour.keys) ? { keys: raw.tour.keys, index: Number(raw.tour.index) || 0 } : null,
  };
}

export function savePrefs(prefs: Prefs) {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* not persisted */ }
}
