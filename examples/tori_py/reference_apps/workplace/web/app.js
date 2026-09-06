if (document.querySelector("workplace-app") && !customElements.get("workplace-app")) {
  const {WorkplaceApp} = await import("/web/workplace-app.js");
  customElements.define("workplace-app", WorkplaceApp);
}

if (document.querySelector("facilities-app") && !customElements.get("facilities-app")) {
  const {FacilitiesApp} = await import("/web/facilities-app.js");
  customElements.define("facilities-app", FacilitiesApp);
}
