import {LitElement, html} from "/assets/lit-core.min.js";

import {adminPanelTemplate} from "/web/admin-panel.js";
import {ApiClient} from "/web/api-client.js";
import {createKeycloak} from "/web/auth.js";
import {bookingCalendarTemplate} from "/web/booking-calendar.js";
import {bookingListTemplate} from "/web/booking-list.js";
import {
  bookingQuery,
  calendarDateFromInstant,
  localDateTimeValue,
} from "/web/calendar.js";
import {floorPlanTemplate} from "/web/floor-plan.js";

const ADMIN_ROLE = "facilities-admin";

export class WorkplaceApp extends LitElement {
  static properties = {
    actor: {state: true},
    tenant: {state: true},
    admin: {state: true},
    offline: {state: true},
    initialized: {state: true},
    resources: {state: true},
    resourcesLoading: {state: true},
    resourcesError: {state: true},
    selected: {state: true},
    availability: {state: true},
    availabilityBusy: {state: true},
    bookingStarts: {state: true},
    bookingEnds: {state: true},
    bookingBusy: {state: true},
    bookingMessage: {state: true},
    bookings: {state: true},
    bookingsLoading: {state: true},
    bookingsError: {state: true},
    calendarDate: {state: true},
    calendarView: {state: true},
    timeZone: {state: true},
    dashboard: {state: true},
    diagnostics: {state: true},
    auditEntries: {state: true},
    adminLoading: {state: true},
    adminError: {state: true},
    cleanupBefore: {state: true},
    cleanupBusy: {state: true},
    outboxMessage: {state: true},
    resourceBusy: {state: true},
    resourceMessage: {state: true},
    mapScale: {state: true},
    mapX: {state: true},
    mapY: {state: true},
  };

  constructor(keycloak = createKeycloak()) {
    super();
    this.keycloak = keycloak;
    this.api = new ApiClient(keycloak);
    this.actor = "Loading identity...";
    this.tenant = "";
    this.admin = false;
    this.offline = !navigator.onLine;
    this.initialized = false;
    this.resources = [];
    this.resourcesLoading = true;
    this.resourcesError = "";
    this.selected = null;
    this.availability = null;
    this.availabilityBusy = false;
    this.bookingStarts = "";
    this.bookingEnds = "";
    this.bookingBusy = false;
    this.bookingMessage = {text: "", error: false};
    this.bookings = [];
    this.bookingsLoading = true;
    this.bookingsError = "";
    this.timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const supportedTimeZones = typeof Intl.supportedValuesOf === "function"
      ? Intl.supportedValuesOf("timeZone")
      : [this.timeZone];
    this.timeZones = [...new Set([this.timeZone, "UTC", ...supportedTimeZones])];
    this.calendarDate = calendarDateFromInstant(new Date(), this.timeZone);
    this.calendarView = "week";
    this.dashboard = null;
    this.diagnostics = null;
    this.auditEntries = [];
    this.adminLoading = false;
    this.adminError = "";
    this.cleanupBefore = localDateTimeValue(new Date(Date.now() - 30 * 86400000));
    this.cleanupBusy = false;
    this.outboxMessage = {text: "", error: false};
    this.resourceBusy = false;
    this.resourceMessage = {text: "", error: false};
    this.mapScale = 1;
    this.mapX = 0;
    this.mapY = 0;
    this.drag = null;
    this.idempotency = null;
    this.bookingsGeneration = 0;

    for (const method of [
      "logout",
      "loadResources",
      "loadBookings",
      "loadAdmin",
      "selectResource",
      "checkAvailability",
      "requestBooking",
      "bookingAction",
      "createResource",
      "cleanupOutbox",
      "zoomOut",
      "zoomReset",
      "zoomIn",
      "startDrag",
      "moveDrag",
      "endDrag",
      "changeCalendarView",
      "changeTimeZone",
      "previousPeriod",
      "nextPeriod",
      "today",
    ]) {
      this[method] = this[method].bind(this);
    }

    this.handleOnline = async () => {
      this.offline = false;
      if (this.initialized) {
        await Promise.all([
          this.loadResources(),
          this.loadBookings(),
          this.admin ? this.loadAdmin() : Promise.resolve(),
        ]);
      }
    };
    this.handleOffline = () => {
      this.offline = true;
    };
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("online", this.handleOnline);
    window.addEventListener("offline", this.handleOffline);
    this.initialize();
  }

  disconnectedCallback() {
    window.removeEventListener("online", this.handleOnline);
    window.removeEventListener("offline", this.handleOffline);
    super.disconnectedCallback();
  }

  async initialize() {
    try {
      const authenticated = await this.keycloak.init({
        onLoad: "login-required",
        flow: "standard",
        pkceMethod: "S256",
        checkLoginIframe: false,
      });
      if (!authenticated) {
        await this.keycloak.login();
        return;
      }
      const claims = this.keycloak.tokenParsed ?? {};
      this.actor = claims.preferred_username ?? claims.sub ?? "Authenticated user";
      this.tenant = claims.tenant_id ?? "no tenant";
      const access = claims.resource_access ?? this.keycloak.resourceAccess ?? {};
      this.admin = (access["tori-space-web"]?.roles ?? []).includes(ADMIN_ROLE);
      this.keycloak.onTokenExpired = () => this.keycloak.updateToken(30);
      this.initialized = true;
      await Promise.all([
        this.loadResources(),
        this.loadBookings(),
        this.admin ? this.loadAdmin() : Promise.resolve(),
      ]);
    } catch (error) {
      this.actor = "Authentication unavailable";
      this.resourcesLoading = false;
      this.bookingsLoading = false;
      this.resourcesError = error.message;
    }
  }

  logout() {
    return this.keycloak.logout({redirectUri: window.location.origin});
  }

  async loadResources() {
    this.resourcesLoading = true;
    this.resourcesError = "";
    try {
      const result = await this.api.request("/api/resources");
      this.resources = Array.isArray(result) ? result : result.items ?? [];
      if (this.selected) {
        this.selected = this.resources.find((item) => item.id === this.selected.id) ?? null;
      }
    } catch (error) {
      this.resourcesError = error.message;
    } finally {
      this.resourcesLoading = false;
    }
  }

  async loadBookings() {
    const generation = ++this.bookingsGeneration;
    this.bookingsLoading = true;
    this.bookingsError = "";
    try {
      const query = bookingQuery(this.calendarDate, this.calendarView);
      const bookings = [];
      const pageSize = 100;
      for (let offset = 0; ; offset += pageSize) {
        query.set("offset", String(offset));
        query.set("limit", String(pageSize));
        const result = await this.api.request(`/api/bookings?${query}`);
        const page = Array.isArray(result) ? result : result.items ?? [];
        bookings.push(...page);
        if (page.length < pageSize) break;
      }
      if (generation !== this.bookingsGeneration) return;
      this.bookings = bookings;
    } catch (error) {
      if (generation !== this.bookingsGeneration) return;
      this.bookingsError = error.message;
    } finally {
      if (generation === this.bookingsGeneration) {
        this.bookingsLoading = false;
      }
    }
  }

  async loadAdmin() {
    if (!this.admin) return;
    this.adminLoading = true;
    this.adminError = "";
    try {
      [this.dashboard, this.diagnostics, this.auditEntries] = await Promise.all([
        this.api.request("/api/facilities/dashboard"),
        this.api.request("/api/outbox/diagnostics"),
        this.api.request("/api/audit"),
      ]);
    } catch (error) {
      this.adminError = error.message;
    } finally {
      this.adminLoading = false;
    }
  }

  selectResource(resource) {
    if (!resource) return;
    this.selected = resource;
    this.availability = null;
    this.bookingMessage = {text: "", error: false};
    if (!this.bookingStarts) {
      const start = new Date(Date.now() + 60 * 60 * 1000);
      start.setMinutes(Math.ceil(start.getMinutes() / 15) * 15, 0, 0);
      const end = new Date(start.getTime() + 60 * 60 * 1000);
      this.bookingStarts = localDateTimeValue(start);
      this.bookingEnds = localDateTimeValue(end);
    }
    this.updateComplete.then(() => this.querySelector("#starts-at")?.focus());
  }

  interval() {
    const startsAt = new Date(this.bookingStarts);
    const endsAt = new Date(this.bookingEnds);
    if (!this.bookingStarts || !this.bookingEnds || startsAt >= endsAt) {
      throw new Error("Choose an end time after the start time.");
    }
    return {startsAt, endsAt};
  }

  async checkAvailability() {
    if (!this.selected) return;
    this.availabilityBusy = true;
    this.availability = null;
    try {
      const {startsAt, endsAt} = this.interval();
      const query = new URLSearchParams({
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
        resource_id: this.selected.id,
      });
      const result = await this.api.request(`/api/availability?${query}`);
      const rows = Array.isArray(result) ? result : result.items ?? [];
      const row = rows.find((item) => item.resource_id === this.selected.id) ?? rows[0];
      this.availability = row?.available
        ? {text: "Available for this interval", open: true}
        : {text: "Unavailable for this interval", open: false};
    } catch (error) {
      this.availability = {text: error.message, open: false, error: true};
    } finally {
      this.availabilityBusy = false;
    }
  }

  async requestBooking(event) {
    event.preventDefault();
    if (!this.selected) return;
    this.bookingBusy = true;
    this.bookingMessage = {text: "", error: false};
    try {
      const {startsAt, endsAt} = this.interval();
      const fingerprint = `${this.selected.id}|${startsAt.toISOString()}|${endsAt.toISOString()}`;
      if (this.idempotency?.fingerprint !== fingerprint) {
        this.idempotency = {fingerprint, key: crypto.randomUUID()};
      }
      const booking = await this.api.request("/api/bookings", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": this.idempotency.key,
        },
        body: JSON.stringify({
          resource_id: this.selected.id,
          starts_at: startsAt.toISOString(),
          ends_at: endsAt.toISOString(),
        }),
      });
      this.bookingMessage = {text: `Booking ${booking.id} accepted.`, error: false};
      this.idempotency = null;
      await Promise.all([this.loadBookings(), this.admin ? this.loadAdmin() : Promise.resolve()]);
    } catch (error) {
      this.bookingMessage = {text: error.message, error: true};
    } finally {
      this.bookingBusy = false;
    }
  }

  async bookingAction(booking, action, needsConfirmation = false) {
    if (needsConfirmation && !window.confirm(`Cancel booking ${booking.id}?`)) return;
    try {
      await this.api.request(`/api/bookings/${encodeURIComponent(booking.id)}/${action}`, {method: "POST"});
      await Promise.all([this.loadBookings(), this.admin ? this.loadAdmin() : Promise.resolve()]);
    } catch (error) {
      this.bookingsError = error.message;
    }
  }

  async createResource(event) {
    event.preventDefault();
    this.resourceBusy = true;
    this.resourceMessage = {text: "", error: false};
    const form = event.currentTarget;
    const fields = new FormData(form);
    try {
      const resource = await this.api.request("/api/resources", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          name: fields.get("name"),
          kind: fields.get("kind"),
          office_id: fields.get("office_id"),
          floor_id: fields.get("floor_id"),
          x: Number(fields.get("x")),
          y: Number(fields.get("y")),
        }),
      });
      this.resourceMessage = {text: `Resource ${resource.name} registered.`, error: false};
      form.reset();
      await this.loadResources();
    } catch (error) {
      this.resourceMessage = {text: error.message, error: true};
    } finally {
      this.resourceBusy = false;
    }
  }

  async cleanupOutbox(event) {
    event.preventDefault();
    this.cleanupBusy = true;
    this.outboxMessage = {text: "", error: false};
    try {
      const cutoff = new Date(this.cleanupBefore);
      if (Number.isNaN(cutoff.getTime())) {
        throw new Error("Choose a valid cleanup cutoff.");
      }
      if (!window.confirm(`Clean delivered outbox records before ${cutoff.toLocaleString()}? This cannot be undone.`)) {
        return;
      }
      const result = await this.api.request("/api/outbox/cleanup", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({before: cutoff.toISOString()}),
      });
      this.outboxMessage = {text: `Removed ${result} delivered record(s).`, error: false};
      await this.loadAdmin();
    } catch (error) {
      this.outboxMessage = {text: error.message, error: true};
    } finally {
      this.cleanupBusy = false;
    }
  }

  changeCalendarView(event) {
    this.calendarView = event.currentTarget.value;
    this.loadBookings();
  }

  changeTimeZone(event) {
    this.timeZone = event.currentTarget.value;
    this.calendarDate = calendarDateFromInstant(new Date(), this.timeZone);
    this.loadBookings();
  }

  shiftPeriod(direction) {
    const next = new Date(this.calendarDate);
    next.setUTCDate(next.getUTCDate() + direction * (this.calendarView === "week" ? 7 : 1));
    this.calendarDate = next;
    this.loadBookings();
  }

  previousPeriod() {
    this.shiftPeriod(-1);
  }

  nextPeriod() {
    this.shiftPeriod(1);
  }

  today() {
    this.calendarDate = calendarDateFromInstant(new Date(), this.timeZone);
    this.loadBookings();
  }

  zoomOut() {
    this.mapScale = Math.max(0.75, this.mapScale - 0.2);
  }

  zoomReset() {
    this.mapScale = 1;
    this.mapX = 0;
    this.mapY = 0;
  }

  zoomIn() {
    this.mapScale = Math.min(2.1, this.mapScale + 0.2);
  }

  startDrag(event) {
    if (event.target.closest("button")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    this.drag = {x: event.clientX, y: event.clientY, mapX: this.mapX, mapY: this.mapY};
  }

  moveDrag(event) {
    if (!this.drag) return;
    this.mapX = this.drag.mapX + event.clientX - this.drag.x;
    this.mapY = this.drag.mapY + event.clientY - this.drag.y;
  }

  endDrag() {
    this.drag = null;
  }

  render() {
    return html`
      <a class="skip-link" href="#resource-list">Skip map and go to resource list</a>
      <header class="masthead">
        <div class="wordmark"><span aria-hidden="true">⌑</span> TORI / SPACE</div>
        <p class="desk-label">Workplace control desk <span>·</span> live reference</p>
        <div class="identity">
          <span class="signal" aria-hidden="true"></span>
          <span id="identity-text">${this.actor}${this.initialized ? ` / ${this.tenant}` : ""}</span>
          <button class="quiet-button" id="logout" type="button" ?hidden=${!this.initialized} @click=${this.logout}>Sign out</button>
        </div>
      </header>

      <main>
        <section class="intro" aria-labelledby="page-title">
          <p class="eyebrow">Building N / level 03</p>
          <h1 id="page-title">Find your working ground.</h1>
          <p>Reserve a desk, room, or focus booth from the floor plan. The gateway receives UTC; the desk displays your chosen browser timezone.</p>
        </section>

        <section class="control-desk" aria-label="Floor plan and selected resource">
          ${floorPlanTemplate(this)}
          <aside class="inspector" aria-live="polite">
            <p class="eyebrow">Selected resource</p>
            <div id="selection-empty" ?hidden=${Boolean(this.selected)}>
              <h2>Choose a marker</h2>
              <p>Select a room or workstation on the plan, or use the accessible list below.</p>
            </div>
            <div id="selection" ?hidden=${!this.selected}>
              <p class="status ${this.availability?.open ? "available" : ""} ${this.availability?.error ? "error" : ""}" id="resource-status">
                ${this.availability?.text ?? "Set an interval to check availability"}
              </p>
              <h2 id="resource-name">${this.selected?.name ?? "—"}</h2>
              <p id="resource-kind">${this.selected?.kind ?? "—"}</p>
              <dl>
                <div><dt>Floor</dt><dd>North / 03</dd></div>
                <div><dt>Equipment</dt><dd id="resource-equipment">${this.selected?.kind === "room" ? "Screen · whiteboard" : "Monitor · power"}</dd></div>
              </dl>
              <form id="booking-form" @submit=${this.requestBooking}>
                <label>Start (browser local time)
                  <input
                    id="starts-at"
                    type="datetime-local"
                    required
                    .value=${this.bookingStarts}
                    @input=${(event) => {
                      this.bookingStarts = event.currentTarget.value;
                      this.availability = null;
                    }}
                  >
                </label>
                <label>End (browser local time)
                  <input
                    id="ends-at"
                    type="datetime-local"
                    required
                    .value=${this.bookingEnds}
                    @input=${(event) => {
                      this.bookingEnds = event.currentTarget.value;
                      this.availability = null;
                    }}
                  >
                </label>
                <button
                  class="secondary-button"
                  id="availability-check"
                  type="button"
                  ?disabled=${this.availabilityBusy}
                  @click=${this.checkAvailability}
                >${this.availabilityBusy ? "Checking…" : "Check availability"}</button>
                <button class="action-button" id="booking-submit" type="submit" ?disabled=${this.bookingBusy}>
                  ${this.bookingBusy ? "Submitting…" : "Mark this time"}
                </button>
              </form>
            </div>
            <p class="response ${this.bookingMessage.error ? "error" : ""}" id="booking-response" role="status">${this.bookingMessage.text}</p>
            ${adminPanelTemplate(this)}
          </aside>
        </section>

        ${bookingCalendarTemplate(this)}
        <section class="list-section" aria-labelledby="resource-list-title">
          <div>
            <p class="eyebrow">No-map alternative</p>
            <h2 id="resource-list-title">Resource register</h2>
          </div>
          <ul id="resource-list" aria-label="Workplace resources">
            ${this.resourcesLoading
              ? html`<li class="list-message">Loading resources…</li>`
              : this.resourcesError
                ? html`<li class="list-message error">Could not load resources: ${this.resourcesError}</li>`
                : this.resources.length
                  ? this.resources.map((resource) => html`
                      <li class="resource-item">
                        <button type="button" @click=${() => this.selectResource(resource)}>${resource.name ?? resource.id}</button>
                        <small>${resource.kind ?? "resource"} · ${resource.office_id ?? "—"} / ${resource.floor_id ?? "—"}</small>
                      </li>
                    `)
                  : html`<li class="list-message">No resources are registered for this tenant yet.</li>`}
          </ul>
        </section>
        ${bookingListTemplate(this)}
      </main>

      <footer>
        <span>TORI SPACE / LOCAL REFERENCE</span>
        <span id="api-status" role="status">${this.offline
          ? "OFFLINE — CHANGES PAUSED"
          : this.resourcesError
            ? "GATEWAY UNAVAILABLE"
            : this.initialized
              ? "GATEWAY LINKED"
              : "Awaiting gateway"}</span>
        <span>NOT A BUILDING SAFETY SYSTEM</span>
      </footer>
    `;
  }
}
