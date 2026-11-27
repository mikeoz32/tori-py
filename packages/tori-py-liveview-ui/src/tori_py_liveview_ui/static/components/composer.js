import {ToriElement} from "./base.js";

export class ToriComposer extends ToriElement {
  static properties = {maxRows: {type: Number, attribute: "max-rows"}, busy: {type: Boolean}};
  connect() {
    this.listen(this, "input", () => this.resize());
    this.listen(this, "keydown", (event) => {
      const field = this.querySelector(".tori-ui-composer__input");
      if (event.target !== field || event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      if (!this.blocked()) this.querySelector("form").requestSubmit();
    });
    this.listen(this, "submit", (event) => {
      if (this.blocked()) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      // Phoenix serializes the form before this next task clears the field.
      this.later(() => {
        const field = this.querySelector(".tori-ui-composer__input");
        if (!field) return;
        field.value = "";
        this.resize();
        field.focus();
      });
    });
    this.observe(this, {childList: true, subtree: true, attributes: true,
      attributeFilter: ["value", "disabled"]});
  }

  blocked() {
    const form = this.querySelector("form");
    const field = this.querySelector(".tori-ui-composer__input");
    return !form || !field || field.disabled || this.busy || !field.value.trim();
  }

  updated() { this.resize(); }

  resize() {
    const field = this.querySelector(".tori-ui-composer__input");
    if (!field || !this.isConnected) return;
    const style = getComputedStyle(field);
    const line = parseFloat(style.lineHeight) || 24;
    const frame = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    const rows = Number(this.maxRows) || 8;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, line * rows + frame)}px`;
  }
}
