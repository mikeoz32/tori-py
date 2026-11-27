import {ToriElement} from "./base.js";

export class ToriDialog extends ToriElement {
  connect() {
    this.listen(this, "tori-ui:open", (event) => {
      const dialog = this.dialog;
      if (event.target !== dialog && event.target !== this) return;
      if (dialog && !dialog.open) dialog.showModal();
    });
    this.listen(this, "tori-ui:close", (event) => {
      if (event.target !== this.dialog && event.target !== this) return;
      this.dialog?.close();
    });
    this.listen(this, "cancel", (event) => {
      if (event.target !== this.dialog) return;
      event.preventDefault();
      this.dismiss();
    }, {capture: true});
    this.listen(this, "click", (event) => {
      const dialog = this.dialog;
      if (!(event.target instanceof Element) || event.target.closest("dialog") !== dialog) return;
      if (event.target === dialog) { this.dismiss(); return; }
      if (event.target.closest("[data-tori-ui-confirm-action]") && dialog.dataset.toriUiOpen === undefined) {
        this.later(() => dialog.close());
      }
    });
    this.observe(this, {childList: true, subtree: true, attributes: true,
      attributeFilter: ["data-tori-ui-open"]});
  }

  get dialog() { return this.querySelector(":scope > dialog"); }

  dismiss() {
    const dialog = this.dialog;
    if (dialog?.dataset.toriUiDismissible !== "false") {
      dialog?.querySelector("[data-tori-ui-dismiss]")?.click();
    }
  }

  updated() {
    const dialog = this.dialog;
    if (!dialog || !this.isConnected) return;
    const wanted = dialog.dataset.toriUiOpen;
    if (wanted === "true" && !dialog.open) dialog.showModal();
    if (wanted === "false" && dialog.open) dialog.close();
  }

  disconnect() { this.dialog?.close(); }
}
