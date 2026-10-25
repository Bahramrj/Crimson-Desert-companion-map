// Our own marker icons: a white glyph on a coloured disc, as SVG data URLs (same origin, no
// game icons). Category ids come from gamedata/markers.py; imported sets fall back to a dot
// with a colour picked from the category id.

const GLYPHS: Record<string, string> = {
  castle: "M5 20V9l2 1V7h2v2h2V7h2v2h2V7h2v3l2-1v11h-5v-4a2 2 0 0 0-4 0v4z",
  gate: "M4 20V8l8-4 8 4v12h-5v-6a3 3 0 0 0-6 0v6z",
  fort: "M8 20V9H6V4h3v2h2V4h2v2h2V4h3v5h-2v11z",
  camp: "M12 4 3 20h18zm0 6 4 8H8z",
  cave: "M3 20c0-8 4-14 9-14s9 6 9 14h-5c0-4-2-7-4-7s-4 3-4 7z",
  ruins: "M4 20v-2h16v2zm2-4V8h3v8zm5 0V5h3v11zm5 0v-6h3v6z",
  temple: "M3 9l9-5 9 5v2H3zm2 3h2v6H5zm4 0h2v6H9zm4 0h2v6h-2zm4 0h2v6h-2zM3 19h18v2H3z",
  village: "M12 4 3 12h3v8h4v-5h4v5h4v-8h3z",
  work: "M14 3l7 7-2 2-2-2-8 8-3-3 8-8-2-2z",
  house: "M4 11l8-6 8 6v9H4zm6 9v-5h4v5z",
  rest: "M12 3c2 3 4 5 4 8a4 4 0 0 1-8 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 0-7zM5 19l14-3 .5 2L5.5 21z",
  meditation: "M12 4a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm-6 9 4-3h4l4 3-1 2-3-2v2l4 3H6l4-3v-2l-3 2z",
  "rest-point": "M12 6a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm0 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  "abyss-artifact": "M12 3l8 9-8 9-8-9z",
  "abyss-bridge": "M3 18v-3c3 0 5-5 9-5s6 5 9 5v3z",
  mine: "M12 3l2.6 5.6 6.1.6-4.6 4.1 1.3 6L12 16.3l-5.4 3 1.3-6-4.6-4.1 6.1-.6z",
  place: "M12 3a6 6 0 0 1 6 6c0 4.5-6 11-6 11S6 13.5 6 9a6 6 0 0 1 6-6zm0 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  "abyss-gate": "M12 3a7 7 0 0 1 7 7v10H5V10a7 7 0 0 1 7-7zm0 4a3 3 0 0 0-3 3v7h6v-7a3 3 0 0 0-3-3z",
  "abyss-ruins": "M12 3l8 9-8 9-8-9z",
  puzzle: "M5 5h5a2 2 0 1 1 4 0h5v5a2 2 0 1 1 0 4v5h-5a2 2 0 1 0-4 0H5v-5a2 2 0 1 0 0-4z",
  challenge: "M5 3h2v18H5zm3 1h10l-2 4 2 4H8z",
  bell: "M12 3a5 5 0 0 1 5 5v5l2 3H5l2-3V8a5 5 0 0 1 5-5zm-2 15h4a2 2 0 0 1-4 0z",
  blacksmith: "M4 9h10l2-3h4v4l-4 2v2h-3v3h3v2H7v-2h3v-3H8a4 4 0 0 1-4-4z",
  inn: "M4 6h2v6h12a2 2 0 0 1 2 2v4h-2v-2H6v2H4zm4 1h3v3H8z",
  stable: "M7 4h3v9a2 2 0 0 0 4 0V4h3v9a5 5 0 0 1-10 0z",
  seed: "M12 20v-6m0 0c-4 0-6-3-6-7 4 0 6 3 6 7zm0 0c4 0 6-3 6-7-4 0-6 3-6 7z",
  goods: "M6 8h12l-1 12H7zm3 0a3 3 0 0 1 6 0",
  trader: "M12 3l9 4-9 4-9-4zm-9 7 9 4 9-4v3l-9 4-9-4z",
  wanted: "M5 3h14v18H5zm3 4v2h8V7zm0 4v2h8v-2zm0 4v2h5v-2z",
  bank: "M12 3l9 5H3zM5 10h2v7H5zm4 0h2v7H9zm4 0h2v7h-2zm4 0h2v7h-2zM3 19h18v2H3z",
  shop: "M4 9l2-5h12l2 5zm0 2h16v9H4zm6 3v6h4v-6z",
  building: "M4 21V8l8-5 8 5v13h-5v-6H9v6z",
  region: "M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2zm6 0v12m6-10v12",
};
const DOT = "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z";

const COLORS: Record<string, string> = {
  castle: "#b45309", gate: "#a16207", fort: "#9a3412", camp: "#dc2626", cave: "#57534e", ruins: "#78716c",
  temple: "#7c3aed", village: "#2563eb", work: "#4d7c0f", house: "#0f766e", rest: "#ea580c", place: "#475569",
  meditation: "#0891b2", "rest-point": "#0284c7", "abyss-artifact": "#c026d3", "abyss-bridge": "#6d28d9", mine: "#e11d48",
  "abyss-gate": "#7e22ce", "abyss-ruins": "#c026d3", puzzle: "#ca8a04", challenge: "#be123c", bell: "#b45309",
  blacksmith: "#44403c", inn: "#9d174d", stable: "#92400e", seed: "#16a34a", goods: "#0d9488", trader: "#1e40af",
  wanted: "#991b1b", bank: "#a16207", shop: "#4338ca", building: "#334155", region: "#7f1d1d",
};
const PALETTE = ["#0e7490", "#7e22ce", "#be123c", "#15803d", "#b45309", "#1d4ed8", "#a21caf", "#4338ca"];

export function categoryColor(category: string): string {
  if (COLORS[category]) return COLORS[category];
  let hash = 0;
  for (const ch of category) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

const cache = new Map<string, string>();

/** Data URL of a 32 px icon; found markers are grey with a tick. */
export function iconUrl(category: string, found: boolean): string {
  const key = `${category}|${found}`;
  let url = cache.get(key);
  if (!url) {
    const fill = found ? "#9ca3af" : categoryColor(category);
    const glyph = found ? "M9.5 16.2 5.8 12.5l1.4-1.4 2.3 2.3 7.3-7.3 1.4 1.4z" : GLYPHS[category] ?? DOT;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">`
      + `<circle cx="16" cy="16" r="13" fill="${fill}" stroke="#fff" stroke-width="2.5"/>`
      + `<path transform="translate(6.4 6.4) scale(.8)" fill="#fff" d="${glyph}"/></svg>`;
    url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    cache.set(key, url);
  }
  return url;
}
