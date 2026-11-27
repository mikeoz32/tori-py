import {ToriElement} from "./base.js";

export class ToriToast extends ToriElement {
  static properties = {duration: {type: Number, attribute: "data-tori-ui-duration"}};

  connect() {
    this.remaining = this.duration;
    this.hovered = this.matches(":hover");
    this.focused = this.contains(document.activeElement);
    this.timer = null;
    this.listen(this, "pointerenter", () => { this.hovered = true; this.pause(); });
    this.listen(this, "pointerleave", () => { this.hovered = false; this.resume(); });
    this.listen(this, "focusin", () => { this.focused = true; this.pause(); });
    this.listen(this, "focusout", (event) => {
      this.focused = event.relatedTarget instanceof Node && this.contains(event.relatedTarget);
      this.resume();
    });
    this.resume();
  }

  updated(changed) {
    if (!changed.has("duration") || !this.connection) return;
    this.clearTimer(this.timer);
    this.timer = null;
    this.remaining = this.duration;
    this.resume();
  }

  pause() {
    if (this.timer === null) return;
    this.clearTimer(this.timer);
    this.timer = null;
    this.remaining = Math.max(this.remaining - (Date.now() - this.started), 1000);
  }

  resume() {
    if (this.timer !== null || this.hovered || this.focused || !(this.remaining > 0)) return;
    this.started = Date.now();
    this.timer = this.later(() => {
      this.timer = null;
      this.querySelector(".tori-ui-toast__dismiss")?.click();
    }, this.remaining);
  }
}
