import Keycloak from "/assets/keycloak.js";

const keycloak = new Keycloak({
  url: "http://localhost:8080",
  realm: "tori-space",
  clientId: "tori-space-web",
});
const state = { selected: null, scale: 1, x: 0, y: 0 };
const $ = (selector) => document.querySelector(selector);

function showResponse(target, message, isError = false) {
  target.textContent = message;
  target.style.color = isError ? "#b33220" : "#3f684e";
}
function applyTransform() {
  $("#floorplan").style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
}
function selectResource(resource) {
  state.selected = resource;
  document.querySelectorAll(".resource").forEach((marker) => marker.classList.toggle("selected", marker.dataset.id === resource.id));
  $("#selection-empty").hidden = true;
  $("#selection").hidden = false;
  $("#resource-name").textContent = resource.name;
  $("#resource-kind").textContent = resource.kind;
  $("#resource-status").textContent = "Availability is checked when you submit a booking";
  $("#resource-equipment").textContent = resource.kind === "room" ? "Screen · whiteboard" : "Monitor · power";
  $("#booking-response").textContent = "";
}
async function api(path, options = {}) {
  await keycloak.updateToken(30);
  const response = await fetch(path, { ...options, headers: { Accept: "application/json", Authorization: `Bearer ${keycloak.token}`, ...options.headers } });
  if (!response.ok) throw new Error(`Gateway returned ${response.status}`);
  return response.status === 204 ? null : response.json();
}
function resourceFromMarker(marker) { return { id: marker.dataset.id, name: marker.dataset.name, kind: marker.dataset.kind }; }
function renderResources(resources) {
  const list = $("#resource-list");
  if (!resources?.length) { list.innerHTML = '<li class="list-message">No resources are registered for this tenant yet.</li>'; return; }
  list.replaceChildren(...resources.map((resource) => {
    const item = document.createElement("li"); item.className = "resource-item";
    const button = document.createElement("button"); button.textContent = resource.name ?? resource.id; button.type = "button";
    button.addEventListener("click", () => selectResource(resource));
    const detail = document.createElement("small"); detail.textContent = `${resource.kind} · ${resource.office_id} / ${resource.floor_id}`;
    item.append(button, detail); return item;
  }));
  document.querySelectorAll(".resource").forEach((marker) => {
    const resource = resources.find((item) => item.name === marker.dataset.name);
    marker.hidden = !resource;
    if (resource) {
      marker.dataset.id = resource.id;
      marker.dataset.kind = resource.kind;
    }
  });
}
async function loadDesk() {
  try {
    const resources = await api("/api/resources");
    renderResources(Array.isArray(resources) ? resources : resources.items);
    $("#api-status").textContent = "GATEWAY LINKED";
  } catch (error) {
    renderResources([]); $("#api-status").textContent = "GATEWAY UNAVAILABLE";
    showResponse($("#booking-response"), `Cannot load live desk: ${error.message}`, true);
  }
}
$("#booking-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selected) return;
  const startsAt = new Date($("#starts-at").value); const endsAt = new Date($("#ends-at").value);
  if (!(startsAt < endsAt)) { showResponse($("#booking-response"), "End must be after start.", true); return; }
  try {
    await api("/api/bookings", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ resource_id: state.selected.id, starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString() }) });
    showResponse($("#booking-response"), "Booking request accepted. Times were sent as UTC.");
  } catch (error) { showResponse($("#booking-response"), `Booking was not accepted: ${error.message}`, true); }
});
$("#resource-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const resource = Object.fromEntries(form); resource.x = Number(resource.x); resource.y = Number(resource.y);
  try { await api("/api/resources", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(resource) }); showResponse($("#resource-response"), "Resource registered."); event.currentTarget.reset(); await loadDesk(); }
  catch (error) { showResponse($("#resource-response"), `Resource was not registered: ${error.message}`, true); }
});
document.querySelectorAll(".resource").forEach((marker) => marker.addEventListener("click", () => selectResource(resourceFromMarker(marker))));
$("#zoom-in").onclick = () => { state.scale = Math.min(2.1, state.scale + .2); applyTransform(); };
$("#zoom-out").onclick = () => { state.scale = Math.max(.75, state.scale - .2); applyTransform(); };
$("#zoom-reset").onclick = () => { Object.assign(state, { scale: 1, x: 0, y: 0 }); applyTransform(); };
let drag; $("#map-viewport").addEventListener("pointerdown", (event) => { drag = { x: event.clientX - state.x, y: event.clientY - state.y }; event.currentTarget.setPointerCapture(event.pointerId); });
$("#map-viewport").addEventListener("pointermove", (event) => { if (!drag) return; state.x = event.clientX - drag.x; state.y = event.clientY - drag.y; applyTransform(); });
$("#map-viewport").addEventListener("pointerup", () => { drag = null; });
$("#logout").onclick = () => keycloak.logout({ redirectUri: location.origin + "/web/" });

try {
  await keycloak.init({ onLoad: "login-required", flow: "standard", pkceMethod: "S256", checkLoginIframe: false });
  const roles = keycloak.resourceAccess?.["tori-space-web"]?.roles ?? [];
  $("#identity-text").textContent = `${keycloak.tokenParsed?.preferred_username ?? "signed in"} / ${keycloak.tokenParsed?.tenant_id ?? "no tenant"}`;
  $("#logout").hidden = false; $("#admin-panel").hidden = !roles.includes("facilities-admin");
  await loadDesk();
} catch (error) { $("#identity-text").textContent = "Sign-in unavailable"; showResponse($("#booking-response"), `Authentication could not start: ${error.message}`, true); }
