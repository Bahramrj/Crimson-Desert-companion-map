// Questions to the user as part of the page (the browser's own prompt() and confirm() look foreign in
// a home-screen app and stop the live map while they are open). A modal <dialog>: the browser keeps
// the focus inside it, Escape cancels, and the focus goes back to where it was.
import { h } from "./ui";

function show<T>(cancelled: T, build: (finish: (value: T) => void) => HTMLElement[]): Promise<T> {
  return new Promise((resolve) => {
    const dialog = h("dialog", { class: "ask", "data-testid": "ask" });
    const finish = (value: T) => {
      if (!dialog.isConnected) return;
      dialog.close();
      dialog.remove();
      resolve(value);
    };
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); finish(cancelled); });        // Escape
    dialog.addEventListener("click", (e) => { if (e.target === dialog) finish(cancelled); });     // the backdrop
    dialog.append(...build(finish));
    document.body.append(dialog);
    dialog.showModal();
  });
}

/** Yes or no. `danger` paints the confirming button as a destructive action. */
export function askConfirm(text: string, ok = "OK", danger = false): Promise<boolean> {
  return show<boolean>(false, (finish) => [
    h("p", { "data-testid": "ask-text" }, text),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn", "data-testid": "ask-cancel", autofocus: true, onclick: () => finish(false) }, "Cancel"),
      h("button", { type: "button", class: `btn ${danger ? "danger-fill" : "primary"}`, "data-testid": "ask-ok", onclick: () => finish(true) }, ok)),
  ]);
}

/** A line of text; null when cancelled or left empty. */
export function askText(title: string, value = "", ok = "Save", maxlength = 60): Promise<string | null> {
  return show<string | null>(null, (finish) => {
    const input = h("input", { type: "text", maxlength: String(maxlength), "aria-label": title, "data-testid": "ask-input", autofocus: true });
    input.value = value;
    const done = () => finish(input.value.trim() || null);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); done(); } });
    queueMicrotask(() => input.select());
    return [
      h("p", { "data-testid": "ask-text" }, title),
      input,
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn", "data-testid": "ask-cancel", onclick: () => finish(null) }, "Cancel"),
        h("button", { type: "button", class: "btn primary", "data-testid": "ask-ok", onclick: done }, ok)),
    ];
  });
}
