// Tiny DOM helpers, the shell's icons and form controls.

type Attrs = Record<string, string | boolean | ((e: Event) => void) | undefined>;
type Child = Node | string | null | undefined | false;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) continue;
    if (typeof value === "function") el.addEventListener(key.replace(/^on/, ""), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children) if (child) el.append(child);
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
// Line icons on a 24 px grid, drawn with a 2 px round stroke (our own; the game markers have their own icons).
const PATHS = {
  follow: "M12 3.5 19 20l-7-3.6L5 20z",
  free: "M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4M9 5l3-2.5L15 5M9 19l3 2.5 3-2.5M5 9l-2.5 3L5 15M19 9l2.5 3L19 15",
  recenter: "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M12 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  realm: "M12 3 3 7.5l9 4.5 9-4.5zM3 12l9 4.5 9-4.5M3 16.5 12 21l9-4.5",
  filters: "M12 21s-6.5-5.8-6.5-11a6.5 6.5 0 0 1 13 0c0 5.2-6.5 11-6.5 11zM12 7.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
  profiles: "M7 3.5h10a1 1 0 0 1 1 1V21l-6-4-6 4V4.5a1 1 0 0 1 1-1z",
  settings: "M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4",
  close: "M6.5 6.5l11 11M17.5 6.5l-11 11",
} as const;

export type IconName = keyof typeof PATHS;

export function icon(name: IconName): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", `icon icon-${name}`);
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", PATHS[name]);
  svg.appendChild(path);
  return svg;
}

/** A row of mutually exclusive buttons. */
export function segmented<T extends string>(name: string, options: readonly [T, string][], value: T, onPick: (v: T) => void): HTMLElement {
  return h("div", { class: "segmented", role: "radiogroup", "aria-label": name },
    ...options.map(([v, label]) => h("button", {
      type: "button", role: "radio", "aria-checked": String(v === value), "data-value": v,
      onclick: () => onPick(v),
    }, label)));
}

export function toggle(label: string, checked: boolean, onChange: (v: boolean) => void, testid?: string): HTMLElement {
  const input = h("input", { type: "checkbox", "data-testid": testid, onchange: (e: Event) => onChange((e.target as HTMLInputElement).checked) });
  input.checked = checked;
  return h("label", { class: "toggle" }, h("span", {}, label), input);
}

/** A labelled range slider showing its value in percent. */
export function slider(label: string, value: number, min: number, max: number, onChange: (v: number) => void, testid?: string): HTMLElement {
  const out = h("span", { class: "slider-value" }, `${Math.round(value * 100)}%`);
  const input = h("input", { type: "range", min: String(min), max: String(max), step: "0.05", "data-testid": testid, "aria-label": label,
    oninput: (e: Event) => {
      const v = Number((e.target as HTMLInputElement).value);
      out.textContent = `${Math.round(v * 100)}%`;
      onChange(v);
    } });
  input.value = String(value);
  return h("label", { class: "slider" }, h("span", { class: "slider-label" }, label), input, out);
}
