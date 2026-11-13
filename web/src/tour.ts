// A short way through a set of markers: nearest neighbour from the start, then 2-opt until no
// swap of two legs makes it shorter. An open path (it does not return to the start).

export interface Stop { x: number; z: number }

const dist = (a: Stop, b: Stop) => Math.hypot(a.x - b.x, a.z - b.z);

/** The order to visit `stops` in, starting from `start`; indices into `stops`. */
export function orderStops(start: Stop, stops: Stop[]): number[] {
  const left = stops.map((_, i) => i);
  const order: number[] = [];
  let at = start;
  while (left.length) {
    let pick = 0;
    for (let i = 1; i < left.length; i++) if (dist(at, stops[left[i]]) < dist(at, stops[left[pick]])) pick = i;
    at = stops[left[pick]];
    order.push(left.splice(pick, 1)[0]);
  }
  const point = (i: number) => (i < 0 ? start : stops[order[i]]);
  for (let improved = true, rounds = 0; improved && rounds < 30; rounds++) {
    improved = false;
    for (let i = 0; i < order.length - 1; i++) {
      for (let j = i + 1; j < order.length; j++) {
        // reversing order[i..j] replaces the legs (i-1, i) and (j, j+1) by (i-1, j) and (i, j+1)
        const before = dist(point(i - 1), point(i)) + (j + 1 < order.length ? dist(point(j), point(j + 1)) : 0);
        const after = dist(point(i - 1), point(j)) + (j + 1 < order.length ? dist(point(i), point(j + 1)) : 0);
        if (after < before - 1e-6) {
          for (let a = i, b = j; a < b; a++, b--) [order[a], order[b]] = [order[b], order[a]];
          improved = true;
        }
      }
    }
  }
  return order;
}

export function pathLength(start: Stop, stops: Stop[], order: number[]): number {
  let total = 0, at = start;
  for (const i of order) { total += dist(at, stops[i]); at = stops[i]; }
  return total;
}
