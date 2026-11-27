import {ToriElement} from "./base.js";

export class ToriTooltip extends ToriElement {
  connect() {
    this.listen(document, "keydown", (event) => {
      if (event.key === "Escape" && this.matches(":hover, :focus-within")) {
        this.setAttribute("data-tori-ui-dismissed", "");
      }
    });
    const restore = () => this.removeAttribute("data-tori-ui-dismissed");
    this.listen(this, "pointerleave", restore);
    this.listen(this, "focusout", (event) => {
      if (!(event.relatedTarget instanceof Node) || !this.contains(event.relatedTarget)) restore();
    });
  }
}
