// Numbers, lists and small helpers the device page's parts share.
import type { Realm } from "./coord";

export const STALE_MS = 2000;
export const TICK_MS = 250;
export const SOURCE_LABEL = { A: "your game files", B: "download", C: "own capture" } as const;

export const SEARCH_LIMIT = 40;
export const SEARCH_CATS = 8;        // categories listed above the markers in the search results
// Panel sections, in this order (gamedata/markers.py GROUPS); other groups follow, "My markers" last.
export const GROUP_ORDER = ["Regions", "Locations", "Services", "Activities", "Quests", "Abyss", "Rest & travel", "Treasures",
  "Collectibles", "Items", "Books & recipes", "Enemies", "Animals", "Crafting", "Mining", "Gathering", "Herbs",
  "Fruits & vegetables"];

export const TRAIL_STEP_M = 5;       // as server/ws.py: a trail point every few metres, a gap after a jump
export const TRAIL_JUMP_M = 150;
export const TRAIL_POINTS = 6000;
export const HUD_ZOOM: [number, number][] = [[4, 7.5], [14, 6.5], [Infinity, 5.5]];   // below this speed (m/s): this zoom
export const TOUR_MAX = 150;         // stops in a route through the markers on screen
export const OFF_WAY_M = 80;         // this far from the road route: look for a new one
export const OFFLINE_MS = 3000;      // without the PC for this long: say so, and grey the map
export const IDLE_MS = 6000;         // while following: the buttons fade after this long without a touch
export const QUICK_PROFILES = 5;
export const NARROW_LANDSCAPE = "(max-height: 500px) and (orientation: landscape)";    // a phone on its side
export const COACH: { button: ButtonKey | null; text: string }[] = [
  { button: "follow", text: "Follow keeps the map on you. Drag the map to look around, then tap here to come back." },
  { button: "markers", text: "Markers: switch kinds on and off, search, and see what is nearest to you." },
  { button: "realm", text: "Pywel or the Abyss. The map changes by itself when you do." },
  { button: null, text: "Hold a finger on the map for the distance to a spot, Navigate, or a marker of your own." },
];
export const NEARBY = 6;             // rows in "Nearest to you"
export const ARRIVE_M = 8;           // navigation ends this close to the target
export const LEVEL_M = 5;            // height differences below this are "the same level"
export const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
export const ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];

export const fmtDist = (m: number) => (m < 1000 ? `${m.toFixed(0)} m` : `${(m / 1000).toFixed(1)} km`);
// Kinds for own markers (mapstore/markers.py MINE_TYPES): the id picks the icon
export const MINE_TYPES: [string, string][] = [["mine", "Marker"], ["chest", "Chest"], ["cave", "Cave"], ["camp", "Camp"], ["village", "Village"],
  ["ore", "Ore"], ["plant", "Plant"], ["fishing", "Fishing spot"], ["quest", "Quest"], ["enemy", "Enemy"], ["puzzle", "Puzzle"],
  ["shop", "Shop"], ["house", "House"], ["landmark", "Landmark"], ["rest", "Rest place"]];
export const SWATCHES = ["", "#dc2626", "#ea580c", "#ca8a04", "#16a34a", "#0891b2", "#2563eb", "#7c3aed", "#db2777", "#475569"];   // "": the kind's colour
export const RESPAWN_CHOICES: [number, string][] = [[0, "Never"], [1, "1 hour"], [3, "3 hours"], [6, "6 hours"], [12, "12 hours"],
  [24, "1 day"], [72, "3 days"], [168, "7 days"]];
export const fmtLeft = (seconds: number) => (seconds < 3600 ? `${Math.max(1, Math.round(seconds / 60))} min`
  : seconds < 48 * 3600 ? `${Math.round(seconds / 3600)} h` : `${Math.round(seconds / 86400)} days`);
export const fmtCoords = (p: { x: number; z: number }) => `x ${p.x.toFixed(0)}, z ${p.z.toFixed(0)}`;

/** A place in the game world: a marker, or a spot picked with a long press. */
export interface Spot { realm: Realm; x: number; z: number; y?: number }
export interface Target extends Spot { key: string | null; name: string }

export type SheetKind = "markers" | "profiles" | "settings";
export type ButtonKey = "follow" | "compass" | "recenter" | "zoomIn" | "zoomOut" | "realm" | "markers" | "profiles" | "settings";
