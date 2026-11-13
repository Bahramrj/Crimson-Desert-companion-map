// The card of the selected marker or picked spot, and the form for an own marker. Functions of the App (main.ts): they take it as their first argument.
import type { App } from "./main";
import type { OwnMarker } from "./api";
import { fmtCoords, fmtDist, fmtLeft, MINE_TYPES, RESPAWN_CHOICES, SOURCE_LABEL, type Spot, SWATCHES, type Target } from "./consts";
import { REALMS } from "./coord";
import { askConfirm } from "./dialog";
import { iconUrl } from "./local/icons";
import { navigate, whereText } from "./navigation";
import { h, icon, type IconName, toggle } from "./ui";

/** The form for an own marker. Its fields write straight into `editing`, so a redraw loses nothing. */
export function editForm(app: App, e: OwnMarker & { id: string | null }): HTMLElement[] {
  const name = h("input", { type: "text", placeholder: "Name", maxlength: "80", "data-testid": "edit-name", "aria-label": "Name",
    oninput: (ev: Event) => { e.name = (ev.target as HTMLInputElement).value; },
    onkeydown: (ev: Event) => { if ((ev as KeyboardEvent).key === "Enter") void app.saveEditing(); } });
  name.value = e.name;
  const notes = h("textarea", { placeholder: "Notes (optional)", maxlength: "500", rows: "2", "data-testid": "edit-notes", "aria-label": "Notes",
    oninput: (ev: Event) => { e.notes = (ev.target as HTMLTextAreaElement).value; } });
  notes.value = e.notes;
  const kind = h("select", { "data-testid": "edit-type", "aria-label": "Kind",
    onchange: (ev: Event) => { e.category = (ev.target as HTMLSelectElement).value; renderCard(app, true); } },
    ...MINE_TYPES.map(([id, label]) => h("option", { value: id }, label)));
  kind.value = e.category;
  const here = app.pos && app.pos.realm === app.shownRealm ? app.pos : null;
  return [
    h("div", { class: "card-head" },
      h("img", { class: "card-icon", src: iconUrl(e.category, false, e.color), alt: "" }),
      h("div", { class: "card-title" }, h("strong", { "data-testid": "card-name" }, e.id ? "Edit marker" : "New marker"),
        h("span", { class: "muted", "data-testid": "card-coords" }, `${REALMS[e.realm].label} · ${fmtCoords(e)}`)),
      h("button", { type: "button", class: "tb", "aria-label": "Cancel", title: "Cancel", onclick: () => app.selectMarker(null) }, icon("close"))),
    h("div", { class: "edit" }, name, notes, h("label", { class: "toggle" }, h("span", {}, "Kind"), kind),
      h("div", { class: "swatches", role: "radiogroup", "aria-label": "Colour" }, ...SWATCHES.map((c) =>
        h("button", { type: "button", class: "swatch", role: "radio", "aria-checked": String(c === e.color), "data-testid": `edit-color-${c || "auto"}`,
          "aria-label": c ? `Colour ${c}` : "The colour of its kind", style: c ? `background:${c}` : "",
          onclick: () => { e.color = c; renderCard(app, true); } }, c ? "" : "A")))),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn small primary", "data-testid": "edit-save", onclick: () => void app.saveEditing() }, "Save"),
      h("button", { type: "button", class: "btn small", "data-testid": "edit-move-here", disabled: !here,
        onclick: () => { if (here) { e.realm = here.realm; e.x = here.x; e.z = here.z; renderCard(app, true); } } }, "Move to my position"),
      h("button", { type: "button", class: "btn small", "data-testid": "edit-move-tap",
        onclick: () => { app.addingByTap = true; app.render(); } }, "Pick on the map")),
  ];
}

export function renderCard(app: App, force = false) {
  if (app.editing) {
    if (app.card.dataset.mode === "edit" && !force) return;     // live updates must not take the keyboard away
    app.card.dataset.mode = "edit";
    app.card.hidden = false;
    app.cardWhere = app.cardSpot = null;
    app.card.replaceChildren(...editForm(app, app.editing));
    return;
  }
  app.card.dataset.mode = "";
  const m = app.selected ? app.markerIndex.get(app.selected) : null;
  const spot: Spot | null = m ?? app.point;
  app.card.hidden = !spot;
  app.cardSpot = spot;
  app.cardWhere = spot ? h("span", { class: "muted", "data-testid": "card-where" }, whereText(app, spot)) : null;
  if (!spot) { app.card.replaceChildren(); app.bridge.setMeasure(null); return; }
  const close = h("button", { type: "button", class: "tb", "aria-label": "Close details", title: "Close",
    onclick: () => app.selectMarker(null) }, icon("close"));
  // "Measure from here" on a picked spot: every card then shows the distance to that spot, with a line on the map
  const from = app.measureFrom;
  const far = from && from.realm === spot.realm ? Math.hypot(spot.x - from.x, spot.z - from.z) : 0;
  app.bridge.setMeasure(from && far > 0.5 && spot.realm === app.shownRealm ? [[from.z, from.x], [spot.z, spot.x]] : null);
  const measured = from && far > 0.5 ? h("p", { class: "muted measure", "data-testid": "card-measure" },
    h("span", {}, `${fmtDist(far)} from the measuring start`),
    h("button", { type: "button", class: "btn small", onclick: () => { app.measureFrom = null; renderCard(app); } }, "Clear")) : null;
  // actions: an icon with a word under it, one row
  const act = (name: IconName, caption: string, testid: string, onclick: () => void,
    opts: { pressed?: boolean; primary?: boolean; danger?: boolean; sub?: string } = {}) =>
    h("button", { type: "button", class: `act${opts.primary ? " primary" : ""}${opts.danger ? " danger" : ""}`, "data-testid": testid,
      "aria-pressed": opts.pressed === undefined ? undefined : String(opts.pressed), onclick },
      icon(name), h("span", {}, caption), opts.sub ? h("small", {}, opts.sub) : null);
  const navButton = (target: Target) => {
    const on = !!app.target && app.target.key === target.key && app.target.x === target.x && app.target.z === target.z;
    return act("route", on ? "Stop" : "Navigate", "card-navigate", () => navigate(app, on ? null : target), { pressed: on });
  };
  if (!m) {                                  // a spot picked with a long press
    const p = app.point!;
    app.card.replaceChildren(
      h("div", { class: "card-head" },
        h("div", { class: "card-title" }, h("strong", { "data-testid": "card-name" }, "Picked spot"),
          h("span", { class: "muted", "data-testid": "card-coords" }, fmtCoords(p)), app.cardWhere), close),
      h("div", { class: "actions" },
        navButton({ ...p, key: null, name: "Picked spot" }),
        act("copy", "Copy", "card-copy", () => void app.copyText(fmtCoords(p))),
        act("pin", "Add marker", "card-add", () => app.addMarker(p.x, p.z)),
        act("ruler", "Measure", "card-measure-start", () => {
          app.measureFrom = { ...p };
          app.notify("Measuring from here: long-press another spot or tap a marker");
          renderCard(app);
        }, { pressed: !!app.measureFrom && app.measureFrom.x === p.x && app.measureFrom.z === p.z })),
      ...(measured ? [measured] : []));
    return;
  }
  const key = app.selected!;
  const set = app.markerData?.sets.find((s) => s.id === m.set);
  const cat = set?.categories.find((c) => c.id === m.category);
  const isFound = app.found.has(key);
  const ends = app.until.get(key);
  const catKey = app.catKey(m);
  const rule = app.rules[catKey] ?? {};
  const respawn = h("select", { "data-testid": "rule-respawn", "aria-label": "Comes back after",
    onchange: (e: Event) => void app.setRule(catKey, { respawnHours: Number((e.target as HTMLSelectElement).value) }) },
    ...RESPAWN_CHOICES.map(([hours, label]) => h("option", { value: String(hours) }, label)));
  respawn.value = String(RESPAWN_CHOICES.some(([hours]) => hours === rule.respawnHours) ? rule.respawnHours : 0);
  const rules = h("details", { class: "rule", "data-testid": "card-rules",
    ontoggle: (e: Event) => { app.rulesOpen = (e.target as HTMLDetailsElement).open; } },
    h("summary", {}, `For all “${cat?.name ?? m.category}”${rule.auto || rule.respawnHours ? " · on" : ""}`),
    toggle("Tick when I get there", !!rule.auto, (v) => void app.setRule(catKey, { auto: v }), "rule-auto"),
    h("label", { class: "toggle" }, h("span", {}, "Comes back after"), respawn));
  rules.open = app.rulesOpen;
  app.card.replaceChildren(
    h("div", { class: "card-head" },
      h("img", { class: "card-icon", src: iconUrl(m.category, isFound, m.color), alt: "" }),
      h("div", { class: "card-title" }, h("strong", { "data-testid": "card-name" }, m.name),
        h("span", { class: "muted" }, cat?.name ?? m.category), app.cardWhere), close),
    ...(m.notes ? [h("p", { class: "notes" }, m.notes)] : []),
    h("div", { class: "actions" },
      act("check", isFound ? "Found" : "Mark found", "card-found", () => void app.setFound(key, !isFound),
        { pressed: isFound, primary: !isFound, sub: isFound && ends ? `back in ${fmtLeft(ends - Date.now() / 1000)}` : undefined }),
      navButton({ realm: m.realm, x: m.x, z: m.z, y: m.y, key, name: m.name }),
      act("recenter", "Show", "card-show", () => app.selectMarker(key, true)),
      m.set === "my-markers" && act("edit", "Edit", "card-edit", () => {
        app.editing = { id: m.id, realm: m.realm, x: m.x, z: m.z, name: m.name, notes: m.notes ?? "", category: m.category, color: m.color ?? "" };
        renderCard(app, true);
      }),
      m.set === "my-markers" && act("trash", "Delete", "card-delete", async () => {
        if (!await askConfirm(`Delete your marker “${m.name}”?`, "Delete", true)) return;
        try { await app.api.deleteMyMarker(m.id); app.selectMarker(null); await app.loadMarkers(); }
        catch (e) { app.notify(`Not deleted: ${(e as Error).message}`); }
      }, { danger: true })),
    ...(measured ? [measured] : []),
    rules,
    h("p", { class: "muted small" }, `${m.province ? `${m.province} · ` : ""}${set?.name ?? m.set}${set ? ` · ${SOURCE_LABEL[set.source]}` : ""} · ${fmtCoords(m)}`),
  );
}
