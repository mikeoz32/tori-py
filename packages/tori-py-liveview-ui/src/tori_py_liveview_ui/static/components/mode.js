import {ToriElement} from "./base.js";

const MODES = ["auto", "light", "dark"];

export class ToriMode extends ToriElement {
  connect() {
    this.listen(this, "click", (event) => {
      const option = event.target instanceof Element
        ? event.target.closest("[data-tori-ui-mode-value]") : null;
      if (!option || option.closest("tori-ui-mode") !== this) return;
      const mode = option.dataset.toriUiModeValue;
      if (!MODES.includes(mode)) return;
      document.documentElement.dataset.toriUiMode = mode;
      try { localStorage.setItem("tori-ui-mode", mode); } catch { /* Storage is optional. */ }
      window.dispatchEvent(new CustomEvent("tori-ui:mode"));
    });
    this.listen(window, "tori-ui:mode", () => this.requestUpdate());
    this.observe(document.documentElement, {
      attributes: true, attributeFilter: ["data-tori-ui-mode"],
    });
  }

  updated() {
    const current = document.documentElement.dataset.toriUiMode ?? "auto";
    for (const option of this.querySelectorAll("[data-tori-ui-mode-value]")) {
      option.setAttribute("aria-pressed", String(option.dataset.toriUiModeValue === current));
    }
  }
}
