import {ToriElement} from "./base.js";

export class ToriPopup extends ToriElement {
  connect() {
    this.wasOpen = this.isOpen;
    this.observe(this, {attributes: true, attributeFilter: ["class"]});
    this.listen(this, "keydown", (event) => {
      if (!this.isOpen || !(event.target instanceof Element) || event.target.closest("tori-ui-popup") !== this) return;
      const trigger = this.querySelector("[aria-expanded]");
      if (event.key === "Escape") {
        event.stopPropagation();
        this.close();
        trigger?.focus();
        return;
      }
      const items = [...this.querySelectorAll('[role="menuitem"]:not(:disabled)')]
        .filter((item) => item.closest("tori-ui-popup") === this);
      if (!items.length) return;
      const index = items.indexOf(document.activeElement);
      const last = items.length - 1;
      const next = {ArrowDown: index >= last ? 0 : index + 1,
        ArrowUp: index <= 0 ? last : index - 1, Home: 0, End: last}[event.key];
      if (next === undefined) return;
      event.preventDefault();
      items[next].focus();
    });
    this.listen(this, "click", (event) => {
      const chosen = event.target instanceof Element ? event.target.closest('[role="menuitem"]') : null;
      if (chosen?.closest("tori-ui-popup") !== this) return;
      this.later(() => { this.close(); this.querySelector("[aria-expanded]")?.focus(); });
    });
    this.listen(this, "focusout", (event) => {
      if (event.relatedTarget instanceof Node && !this.contains(event.relatedTarget)) this.close();
    });
  }

  get isOpen() { return this.classList.contains("tori-ui-popup--open"); }
  close() {
    if (this.isOpen) globalThis.liveSocket.execJS(this, this.getAttribute("phx-click-away"));
  }
  updated() {
    if (this.isOpen && !this.wasOpen) {
      const panel = this.querySelector(".tori-ui-popup__panel");
      (panel?.querySelector('[role="menuitem"]:not(:disabled)') ?? panel)?.focus();
    }
    this.wasOpen = this.isOpen;
  }
}
