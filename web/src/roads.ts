// Routes along the game's roads. "Import from game files" stores a small grid with the Pywel map
// (gamedata/worldmap.py road_grid: one cell is 12 m; sea, land or road), and the path is searched
// here with A*: roads are cheap, open land costs four times as much, water far more. So a route
// takes the road where there is one and still reaches places away from it.

export interface RoadGrid {
  n: number;                                    // cells per side
  bounds: [number, number, number, number];     // game xmin, zmin, xmax, zmax the grid covers
  cells: Uint8Array;                            // 0 sea, 1 land, 2 road; row 0 is the north edge
}

export interface RoadPath { points: [number, number][]; length: number }

const COST = [25, 4, 1];
const MARGIN = 150;          // cells searched around the box of start and goal (1.8 km)
const MAX_EXPANDED = 900_000;

export async function loadRoads(url: string, bounds: RoadGrid["bounds"]): Promise<RoadGrid> {
  const img = new Image();
  img.src = url;
  await img.decode();
  const n = img.naturalWidth;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = n;
  const g = canvas.getContext("2d", { willReadFrequently: true });
  if (!g) throw new Error("no canvas");
  g.drawImage(img, 0, 0);
  const rgba = g.getImageData(0, 0, n, n).data;
  const cells = new Uint8Array(n * n);
  for (let i = 0; i < cells.length; i++) {
    const v = rgba[i * 4];
    cells[i] = v > 200 ? 2 : v > 60 ? 1 : 0;
  }
  return { n, bounds, cells };
}

/** The cheapest way from one game position [x, z] to another, as game positions; null when a
 *  position is off the grid or the search gets too large (the caller then draws a straight line). */
export function findPath(grid: RoadGrid, from: [number, number], to: [number, number]): RoadPath | null {
  const { n, cells } = grid;
  const [xmin, zmin, xmax, zmax] = grid.bounds;
  const col = (x: number) => Math.floor((x - xmin) / (xmax - xmin) * n);
  const row = (z: number) => Math.floor((zmax - z) / (zmax - zmin) * n);
  const sx = col(from[0]), sy = row(from[1]), tx = col(to[0]), ty = row(to[1]);
  if (Math.min(sx, sy, tx, ty) < 0 || Math.max(sx, sy, tx, ty) >= n) return null;
  const x0 = Math.max(0, Math.min(sx, tx) - MARGIN), y0 = Math.max(0, Math.min(sy, ty) - MARGIN);
  const w = Math.min(n, Math.max(sx, tx) + MARGIN + 1) - x0, h = Math.min(n, Math.max(sy, ty) + MARGIN + 1) - y0;
  const best = new Float32Array(w * h).fill(Infinity);
  const prev = new Int32Array(w * h).fill(-1);
  const done = new Uint8Array(w * h);
  const start = (sy - y0) * w + (sx - x0), goal = (ty - y0) * w + (tx - x0);
  // a binary heap of [estimate, cell]
  const heapF: number[] = [], heapI: number[] = [];
  const push = (f: number, i: number) => {
    let k = heapF.length;
    heapF.push(f); heapI.push(i);
    while (k > 0) {
      const p = (k - 1) >> 1;
      if (heapF[p] <= f) break;
      heapF[k] = heapF[p]; heapI[k] = heapI[p];
      k = p;
    }
    heapF[k] = f; heapI[k] = i;
  };
  const pop = () => {
    const top = heapI[0];
    const f = heapF.pop()!, i = heapI.pop()!;
    const size = heapF.length;
    if (size) {
      let k = 0;
      for (;;) {
        let c = 2 * k + 1;
        if (c >= size) break;
        if (c + 1 < size && heapF[c + 1] < heapF[c]) c++;
        if (heapF[c] >= f) break;
        heapF[k] = heapF[c]; heapI[k] = heapI[c];
        k = c;
      }
      heapF[k] = f; heapI[k] = i;
    }
    return top;
  };
  const gx = tx - x0, gy = ty - y0;
  best[start] = 0;
  push(0, start);
  let expanded = 0;
  while (heapF.length) {
    const cur = pop();
    if (done[cur]) continue;
    done[cur] = 1;
    if (cur === goal) break;
    if (++expanded > MAX_EXPANDED) return null;
    const cx = cur % w, cy = (cur - cx) / w;
    for (let dy = -1; dy <= 1; dy++) {
      const ny = cy + dy;
      if (ny < 0 || ny >= h) continue;
      for (let dx = -1; dx <= 1; dx++) {
        const nx = cx + dx;
        if ((!dx && !dy) || nx < 0 || nx >= w) continue;
        const next = ny * w + nx;
        if (done[next]) continue;
        const cost = best[cur] + COST[cells[(ny + y0) * n + nx + x0]] * (dx && dy ? Math.SQRT2 : 1);
        if (cost < best[next]) {
          best[next] = cost;
          prev[next] = cur;
          push(cost + Math.hypot(gx - nx, gy - ny), next);
        }
      }
    }
  }
  if (!done[goal]) return null;
  const cellsOnPath: number[] = [];
  for (let c = goal; c !== -1; c = prev[c]) cellsOnPath.push(c);
  cellsOnPath.reverse();
  const size = (xmax - xmin) / n;
  const centre = (c: number): [number, number] => {
    const cx = c % w, cy = (c - cx) / w;
    return [xmin + (cx + x0 + 0.5) * size, zmax - (cy + y0 + 0.5) * size];
  };
  // the exact ends, and of the cells between them only those where the way turns
  const points: [number, number][] = [from];
  for (let i = 1; i < cellsOnPath.length - 1; i++) {
    const a = cellsOnPath[i - 1], b = cellsOnPath[i], c = cellsOnPath[i + 1];
    if (b - a !== c - b) points.push(centre(b));
  }
  points.push(to);
  let length = 0;
  for (let i = 1; i < points.length; i++) length += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  return { points, length };
}
