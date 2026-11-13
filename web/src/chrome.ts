// Around the map: the phone sheet's grip, buttons that step back while following, the quick profile list, first-run tips. Functions of the App (main.ts): they take it as their first argument.
import type { App } from "./main";
import type { Profile } from "./api";
import { COACH, IDLE_MS, QUICK_PROFILES } from "./consts";
import { savePrefs } from "./prefs";
import { h } from "./ui";

/** On a phone the panel is a bottom sheet with three heights. Its grip is dragged, or tapped to go to the next height. */
export function sheetGrip(app: App) {
  const stops = ["peek", "half", "full"] as const;
  let startY = 0, startH = 0, moved = false, dragging = false;
  const setStop = (stop: typeof stops[number]) => {
    app.prefs.sheetStop = stop;
    savePrefs(app.prefs);
    app.sheet.dataset.stop = stop;
  };
  app.sheet.addEventListener("pointerdown", (e) => {
    const grip = (e.target as HTMLElement).closest<HTMLElement>(".sheet-grip");
    if (!grip) return;
    dragging = true;
    moved = false;
    startY = e.clientY;
    startH = app.sheet.getBoundingClientRect().height;
    grip.setPointerCapture(e.pointerId);
  });
  app.sheet.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    if (Math.abs(e.clientY - startY) > 6) moved = true;
    if (!moved) return;
    app.sheet.style.transition = "none";
    app.sheet.style.height = `${Math.max(80, startH - (e.clientY - startY))}px`;
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    const part = app.sheet.getBoundingClientRect().height / window.innerHeight;
    app.sheet.style.transition = app.sheet.style.height = "";
    if (moved) setStop(part < 0.42 ? "peek" : part < 0.7 ? "half" : "full");
    else setStop(stops[(stops.indexOf(app.prefs.sheetStop) + 1) % stops.length]);
  };
  app.sheet.addEventListener("pointerup", end);
  app.sheet.addEventListener("pointercancel", end);
}

export function canIdle(app: App) {
  return app.prefs.autoHide && app.layout.follow && !!app.pos && !app.sheetKind && !app.selected && !app.point && !app.editing
    && !app.calibrating && !app.addingByTap && !app.hud && app.coachStep < 0 && app.quick.hidden;
}

/** Any touch or key: the buttons are back, and the count to hiding them starts again. */
export function wake(app: App) {
  document.body.removeAttribute("data-idle");
  clearTimeout(app.idleTimer);
  app.idleTimer = window.setTimeout(() => {
    if (canIdle(app)) document.body.setAttribute("data-idle", "");
    else wake(app);                         // not now (a panel is open, ...): look again later
  }, IDLE_MS);
}

export function quickProfiles(app: App, button: HTMLElement) {
  let timer = 0, held = false;
  button.addEventListener("pointerdown", () => {
    held = false;
    clearTimeout(timer);
    timer = window.setTimeout(() => { held = true; openQuick(app, button); }, 500);
  });
  for (const type of ["pointerup", "pointerleave", "pointercancel"]) button.addEventListener(type, () => clearTimeout(timer));
  button.addEventListener("click", (e) => { if (held) { e.stopImmediatePropagation(); held = false; } }, true);    // the hold is not a tap
  button.addEventListener("contextmenu", (e) => { e.preventDefault(); clearTimeout(timer); openQuick(app, button); });
}

export function openQuick(app: App, button: HTMLElement) {
  const recent = app.prefs.recentProfiles.map((id) => app.profiles.find((p) => p.id === id)).filter((p): p is Profile => !!p);
  const rest = app.profiles.filter((p) => !recent.includes(p)).sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
  const list = [...recent, ...rest].slice(0, QUICK_PROFILES);
  if (!list.length) { app.openSheet("profiles"); return; }
  const close = () => { app.quick.hidden = true; };
  app.quick.replaceChildren(
    ...list.map((p) => h("button", { type: "button", role: "menuitem", "data-testid": "quick-profile", class: p.id === app.prefs.lastProfileId ? "active" : "",
      onclick: () => { close(); app.applyProfile(p); } }, p.name)),
    h("button", { type: "button", role: "menuitem", class: "more", "data-testid": "quick-all",
      onclick: () => { close(); if (app.sheetKind !== "profiles") app.openSheet("profiles"); } }, "All profiles…"));
  app.quick.hidden = false;
  placeNear(app.quick, button);
}

/** Put a small floating box next to a control, on the side with room, inside the screen. */
export function placeNear(box: HTMLElement, anchor: HTMLElement | null) {
  const w = window.innerWidth, hgt = window.innerHeight, gap = 12;
  const size = box.getBoundingClientRect();
  let left = (w - size.width) / 2, top = (hgt - size.height) / 2;
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cy > hgt * 0.66) { top = r.top - gap - size.height; left = cx - size.width / 2; }            // a bottom bar: above it
    else if (cx > w * 0.66) { left = r.left - gap - size.width; top = cy - size.height / 2; }        // at the right: to its left
    else if (cx < w * 0.34) { left = r.right + gap; top = cy - size.height / 2; }
    else { top = r.bottom + gap; left = cx - size.width / 2; }
  }
  box.style.left = `${Math.max(8, Math.min(w - size.width - 8, left))}px`;
  box.style.top = `${Math.max(8, Math.min(hgt - size.height - 8, top))}px`;
}

export function showCoach(app: App, step: number) {
  document.querySelector(".coach-target")?.classList.remove("coach-target");
  const done = step < 0 || step >= COACH.length;
  app.coachStep = done ? -1 : step;
  app.coach.hidden = done;
  if (done) {
    if (!app.prefs.coached) { app.prefs.coached = true; savePrefs(app.prefs); }
    return;
  }
  const tip = COACH[step];
  const anchor = tip.button ? app.buttons[tip.button] : null;
  anchor?.classList.add("coach-target");
  const last = step === COACH.length - 1;
  app.coach.replaceChildren(
    h("p", { "data-testid": "coach-text" }, tip.text),
    h("div", { class: "row" },
      h("span", { class: "muted" }, `${step + 1} of ${COACH.length}`),
      last ? null : h("button", { type: "button", class: "btn small", "data-testid": "coach-skip", onclick: () => showCoach(app, -1) }, "Skip"),
      h("button", { type: "button", class: "btn small primary", "data-testid": "coach-next", onclick: () => showCoach(app, step + 1) }, last ? "Got it" : "Next")));
  placeNear(app.coach, anchor);
}
