// Realms, the world extent, and image px <-> game conversion (same rules as mapstore/georef.py).

export type Realm = "pywel" | "abyss";

export const REALMS: Record<Realm, { label: string }> = {
  pywel: { label: "Pywel" },
  abyss: { label: "Abyss" },
};

/** Extent of the game's world-map layers: [xmin, zmin, xmax, zmax]. */
export const WORLD = [-16384, -11267, 3076, 8193] as const;

export interface Georef {
  origin: [number, number]; // game [x, z] of the image's top-left corner
  mpp: number;              // metres per pixel
}

/** Game (x, z) -> image pixel (u right, v down). */
export function gameToPx(g: Georef, x: number, z: number): [number, number] {
  return [(x - g.origin[0]) / g.mpp, (g.origin[1] - z) / g.mpp];
}
