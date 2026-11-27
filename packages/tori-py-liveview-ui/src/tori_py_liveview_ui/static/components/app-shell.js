import {ToriElement} from "./base.js";

export class ToriAppShell extends ToriElement {
  connect() {
    this.listen(window, "phx:navigate", () => {
      if (!this.classList.contains("tori-ui-app-shell--sidebar-open")) return;
      const command = this.getAttribute("phx-window-keydown");
      if (command) globalThis.liveSocket.execJS(this, command);
    });
  }
}
