import {FacilitiesApp, WorkplaceApp} from "/web/workplace-app.js";

if (!customElements.get("workplace-app")) {
  customElements.define("workplace-app", WorkplaceApp);
}

if (!customElements.get("facilities-app")) {
  customElements.define("facilities-app", FacilitiesApp);
}
