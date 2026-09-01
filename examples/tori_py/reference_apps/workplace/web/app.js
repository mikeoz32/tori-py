import {WorkplaceApp} from "/web/workplace-app.js";

if (!customElements.get("workplace-app")) {
  customElements.define("workplace-app", WorkplaceApp);
}
