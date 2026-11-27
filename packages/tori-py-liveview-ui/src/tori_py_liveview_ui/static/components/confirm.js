import {ToriElement} from "./base.js";

export class ToriConfirm extends ToriElement {
  connect() {
    this.listen(this, "click", (event) => {
      const button = event.target instanceof Element ? event.target.closest("button") : null;
      if (!button || button.closest("tori-ui-confirm") !== this || button.disabled) return;
      if (!window.confirm(button.getAttribute("data-tori-ui-confirm"))) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, {capture: true});
  }
}
