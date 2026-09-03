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
const EMPTY_RESOURCE_FILTERS = Object.freeze({
  office_id: "",
  floor_id: "",
  kind: "",
  equipment: "",
  min_capacity: "",
  availability_from: "",
  availability_to: "",
});
const WORKSPACES = Object.freeze({
  reserve: {
    eyebrow: "Building N / Level 03",
    title: "Choose where work happens.",
    description: "Find the right setting, check a time, and reserve it without leaving the floor plan.",
  },
  schedule: {
    eyebrow: "Personal schedule",
    title: "Make the week legible.",
    description: "See every reservation in local time, then check in, reschedule, or cancel from one place.",
  },
  facilities: {
    eyebrow: "Facilities operations",
    title: "Keep the workplace moving.",
    description: "Manage spaces and office policy while monitoring delivery health and the audit trail.",
  },
});

function equipmentFrom(value) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function isBookable(resource) {
  return resource?.active !== false;
}

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
    resourceFilters: {state: true},
    recurringBusy: {state: true},
    rescheduling: {state: true},
    rescheduleStarts: {state: true},
    rescheduleEnds: {state: true},
    rescheduleBusy: {state: true},
    bookingsMessage: {state: true},
    resourceOffset: {state: true},
    resourceHasNext: {state: true},
    officePolicy: {state: true},
    policyOfficeId: {state: true},
    officePolicyBusy: {state: true},
    officePolicyMessage: {state: true},
    selectedOfficePolicy: {state: true},
    cancellationBusy: {state: true},
    activeWorkspace: {state: true},
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
    this.resourceFilters = {...EMPTY_RESOURCE_FILTERS};
    this.recurringBusy = false;
    this.rescheduling = null;
    this.rescheduleStarts = "";
    this.rescheduleEnds = "";
    this.rescheduleBusy = false;
    this.bookingsMessage = {text: "", error: false};
    this.resourceOffset = 0;
    this.resourcePageSize = 20;
    this.resourceHasNext = false;
    this.officePolicy = null;
    this.policyOfficeId = "building-n";
    this.officePolicyBusy = false;
    this.officePolicyMessage = {text: "", error: false};
    this.selectedOfficePolicy = null;
    this.cancellationBusy = false;
    this.activeWorkspace = "reserve";
    this.drag = null;
    this.idempotency = null;
    this.recurringIdempotency = null;
    this.rescheduleIdempotency = null;
    this.cancellationIdempotency = null;
    this.resourcesGeneration = 0;
    this.availabilityGeneration = 0;
    this.bookingsGeneration = 0;

    for (const method of [
      "logout",
      "loadResources",
      "loadBookings",
      "loadAdmin",
      "loadAdminOfficePolicy",
      "loadOfficePolicy",
      "selectResource",
      "checkAvailability",
      "requestBooking",
      "requestRecurringBooking",
      "bookingAction",
      "cancelBooking",
      "beginReschedule",
      "saveReschedule",
      "cancelReschedule",
      "applyResourceFilters",
      "clearResourceFilters",
      "previousResourcePage",
      "nextResourcePage",
      "setResourceFilter",
      "createResource",
      "updateResource",
      "deactivateResource",
      "reactivateResource",
      "cleanupOutbox",
      "saveOfficePolicy",
      "setPolicyOffice",
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
      "changeWorkspace",
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
    const generation = ++this.resourcesGeneration;
    this.resourcesLoading = true;
    this.resourcesError = "";
    try {
      const filters = this.resourceFilters;
      const query = new URLSearchParams();
      for (const name of ["office_id", "floor_id", "kind", "min_capacity"]) {
        if (filters[name]) query.set(name, filters[name]);
      }
      for (const equipment of equipmentFrom(filters.equipment)) {
        query.append("equipment", equipment);
      }
      if (filters.availability_from && filters.availability_to) {
        query.set("availability_from", new Date(filters.availability_from).toISOString());
        query.set("availability_to", new Date(filters.availability_to).toISOString());
      }
      if (this.admin) query.set("include_inactive", "true");
      query.set("offset", String(this.resourceOffset));
      query.set("limit", String(this.resourcePageSize));
      const result = await this.api.request(`/api/resources${query.size ? `?${query}` : ""}`);
      if (generation !== this.resourcesGeneration) return;
      this.resources = Array.isArray(result) ? result : result.items ?? [];
      this.resourceHasNext = this.resources.length === this.resourcePageSize;
      if (this.selected) {
        this.selected = this.resources.find((item) => item.id === this.selected.id) ?? null;
      }
    } catch (error) {
      if (generation !== this.resourcesGeneration) return;
      this.resourcesError = error.message;
    } finally {
      if (generation === this.resourcesGeneration) {
        this.resourcesLoading = false;
      }
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
      [this.dashboard, this.diagnostics, this.auditEntries, this.officePolicy] = await Promise.all([
        this.api.request("/api/facilities/dashboard"),
        this.api.request("/api/outbox/diagnostics"),
        this.api.request("/api/audit"),
        this.api.request(`/api/offices/${encodeURIComponent(this.policyOfficeId)}/policy`),
      ]);
    } catch (error) {
      this.adminError = error.message;
    } finally {
      this.adminLoading = false;
    }
  }

  setPolicyOffice(event) {
    this.policyOfficeId = event.currentTarget.value;
  }

  async loadAdminOfficePolicy() {
    const officeId = this.policyOfficeId.trim();
    if (!officeId) return;
    this.officePolicyBusy = true;
    this.officePolicyMessage = {text: "", error: false};
    try {
      this.officePolicy = await this.api.request(
        `/api/offices/${encodeURIComponent(officeId)}/policy`,
      );
    } catch (error) {
      this.officePolicy = null;
      this.officePolicyMessage = {text: error.message, error: true};
    } finally {
      this.officePolicyBusy = false;
    }
  }

  selectResource(resource) {
    if (!resource) return;
    this.selected = resource;
    this.clearAvailability();
    this.bookingMessage = {text: "", error: false};
    this.loadOfficePolicy(resource.office_id);
    if (!this.bookingStarts) {
      const start = new Date(Date.now() + 60 * 60 * 1000);
      start.setMinutes(Math.ceil(start.getMinutes() / 15) * 15, 0, 0);
      const end = new Date(start.getTime() + 60 * 60 * 1000);
      this.bookingStarts = localDateTimeValue(start);
      this.bookingEnds = localDateTimeValue(end);
    }
    this.updateComplete.then(() => this.querySelector("#starts-at")?.focus());
  }

  clearAvailability() {
    this.availabilityGeneration += 1;
    this.availabilityBusy = false;
    this.availability = null;
  }

  async loadOfficePolicy(officeId) {
    if (!officeId) return;
    try {
      const policy = await this.api.request(`/api/offices/${encodeURIComponent(officeId)}/policy`);
      if (this.selected?.office_id === officeId) this.selectedOfficePolicy = policy;
    } catch (error) {
      if (this.selected?.office_id === officeId) {
        this.selectedOfficePolicy = null;
        this.bookingMessage = {text: error.message, error: true};
      }
    }
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
    if (!this.selected || !isBookable(this.selected)) return;
    const generation = ++this.availabilityGeneration;
    const resourceId = this.selected.id;
    this.availabilityBusy = true;
    this.availability = null;
    try {
      const {startsAt, endsAt} = this.interval();
      const query = new URLSearchParams({
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
        resource_id: resourceId,
      });
      const result = await this.api.request(`/api/availability?${query}`);
      if (generation !== this.availabilityGeneration) return;
      const rows = Array.isArray(result) ? result : result.items ?? [];
      const row = rows.find((item) => item.resource_id === resourceId) ?? rows[0];
      this.availability = row?.available
        ? {text: "Available for this interval", open: true}
        : {text: "Unavailable for this interval", open: false};
    } catch (error) {
      if (generation !== this.availabilityGeneration) return;
      this.availability = {text: error.message, open: false, error: true};
    } finally {
      if (generation === this.availabilityGeneration) {
        this.availabilityBusy = false;
      }
    }
  }

  async requestBooking(event) {
    event.preventDefault();
    if (!this.selected || !isBookable(this.selected)) return;
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

  async requestRecurringBooking(event) {
    event.preventDefault();
    if (!this.selected || !isBookable(this.selected)) return;
    this.recurringBusy = true;
    this.bookingMessage = {text: "", error: false};
    try {
      const {startsAt, endsAt} = this.interval();
      const form = new FormData(event.currentTarget);
      const recurrence = String(form.get("recurrence"));
      const occurrenceCount = Number(form.get("occurrence_count"));
      if (!Number.isInteger(occurrenceCount) || occurrenceCount < 2 || occurrenceCount > 52) {
        throw new Error("Choose between 2 and 52 occurrences.");
      }
      const fingerprint = `${this.selected.id}|${startsAt.toISOString()}|${endsAt.toISOString()}|${recurrence}|${occurrenceCount}`;
      if (this.recurringIdempotency?.fingerprint !== fingerprint) {
        this.recurringIdempotency = {fingerprint, key: crypto.randomUUID()};
      }
      const bookings = await this.api.request("/api/bookings/recurring", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": this.recurringIdempotency.key,
        },
        body: JSON.stringify({
          resource_id: this.selected.id,
          starts_at: startsAt.toISOString(),
          ends_at: endsAt.toISOString(),
          recurrence,
          occurrence_count: occurrenceCount,
        }),
      });
      this.bookingMessage = {text: `${Array.isArray(bookings) ? bookings.length : "Recurring"} booking(s) accepted.`, error: false};
      this.recurringIdempotency = null;
      await Promise.all([this.loadBookings(), this.admin ? this.loadAdmin() : Promise.resolve()]);
    } catch (error) {
      this.bookingMessage = {text: error.message, error: true};
    } finally {
      this.recurringBusy = false;
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

  async cancelBooking(booking, scope = "one") {
    const label = scope === "one"
      ? "this occurrence"
      : scope === "this-and-following"
        ? "this and following occurrences"
        : "the entire series";
    if (!window.confirm(`Cancel ${label}?`)) return;
    const fingerprint = `${booking.id}|${scope}`;
    if (this.cancellationIdempotency?.fingerprint !== fingerprint) {
      this.cancellationIdempotency = {fingerprint, key: crypto.randomUUID()};
    }
    this.cancellationBusy = true;
    this.bookingsMessage = {text: "", error: false};
    try {
      const result = await this.api.request(`/api/bookings/${encodeURIComponent(booking.id)}/cancel`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": this.cancellationIdempotency.key,
        },
        body: JSON.stringify({scope}),
      });
      const count = Array.isArray(result) ? result.length : 1;
      this.bookingsMessage = {text: `Cancelled ${count} booking(s).`, error: false};
      this.cancellationIdempotency = null;
      await Promise.all([this.loadBookings(), this.admin ? this.loadAdmin() : Promise.resolve()]);
    } catch (error) {
      this.bookingsMessage = {text: error.message, error: true};
    } finally {
      this.cancellationBusy = false;
    }
  }

  beginReschedule(booking) {
    this.rescheduling = booking;
    this.rescheduleStarts = localDateTimeValue(new Date(booking.starts_at));
    this.rescheduleEnds = localDateTimeValue(new Date(booking.ends_at));
    this.rescheduleIdempotency = null;
    this.bookingsMessage = {text: "", error: false};
  }

  cancelReschedule() {
    this.rescheduling = null;
    this.rescheduleIdempotency = null;
  }

  async saveReschedule(event) {
    event.preventDefault();
    const booking = this.rescheduling;
    if (!booking) return;
    this.rescheduleBusy = true;
    this.bookingsMessage = {text: "", error: false};
    try {
      const startsAt = new Date(this.rescheduleStarts);
      const endsAt = new Date(this.rescheduleEnds);
      if (!this.rescheduleStarts || !this.rescheduleEnds || startsAt >= endsAt) {
        throw new Error("Choose an end time after the start time.");
      }
      const fingerprint = `${booking.id}|${startsAt.toISOString()}|${endsAt.toISOString()}`;
      if (this.rescheduleIdempotency?.fingerprint !== fingerprint) {
        this.rescheduleIdempotency = {fingerprint, key: crypto.randomUUID()};
      }
      await this.api.request(`/api/bookings/${encodeURIComponent(booking.id)}/reschedule`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": this.rescheduleIdempotency.key,
        },
        body: JSON.stringify({
          starts_at: startsAt.toISOString(),
          ends_at: endsAt.toISOString(),
        }),
      });
      this.bookingsMessage = {text: `Booking ${booking.id} rescheduled.`, error: false};
      this.rescheduling = null;
      this.rescheduleIdempotency = null;
      await Promise.all([this.loadBookings(), this.admin ? this.loadAdmin() : Promise.resolve()]);
    } catch (error) {
      this.bookingsMessage = {text: error.message, error: true};
    } finally {
      this.rescheduleBusy = false;
    }
  }

  applyResourceFilters(event) {
    event.preventDefault();
    if (Boolean(this.resourceFilters.availability_from) !== Boolean(this.resourceFilters.availability_to)) {
      this.resourcesError = "Availability filtering needs both a start and end.";
      return;
    }
    this.resourceOffset = 0;
    this.loadResources();
  }

  clearResourceFilters() {
    this.resourceFilters = {...EMPTY_RESOURCE_FILTERS};
    this.resourcesError = "";
    this.resourceOffset = 0;
    this.loadResources();
  }

  previousResourcePage() {
    this.resourceOffset = Math.max(0, this.resourceOffset - this.resourcePageSize);
    this.loadResources();
  }

  nextResourcePage() {
    if (!this.resourceHasNext) return;
    this.resourceOffset += this.resourcePageSize;
    this.loadResources();
  }

  setResourceFilter(name, event) {
    this.resourceFilters = {
      ...this.resourceFilters,
      [name]: event.currentTarget.value,
    };
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
          equipment: equipmentFrom(fields.get("equipment")),
          capacity: Number(fields.get("capacity")),
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

  async updateResource(event, resource) {
    event.preventDefault();
    this.resourceBusy = true;
    const fields = new FormData(event.currentTarget);
    try {
      await this.api.request(`/api/resources/${encodeURIComponent(resource.id)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          name: fields.get("name"),
          office_id: fields.get("office_id"),
          floor_id: fields.get("floor_id"),
          kind: fields.get("kind"),
          x: Number(fields.get("x")),
          y: Number(fields.get("y")),
          equipment: equipmentFrom(fields.get("equipment")),
          capacity: Number(fields.get("capacity")),
        }),
      });
      this.resourceMessage = {text: `Resource ${resource.id} updated.`, error: false};
      await this.loadResources();
    } catch (error) {
      this.resourceMessage = {text: error.message, error: true};
    } finally {
      this.resourceBusy = false;
    }
  }

  async deactivateResource(resource) {
    if (!window.confirm(`Deactivate ${resource.name}?`)) return;
    this.resourceBusy = true;
    try {
      await this.api.request(`/api/resources/${encodeURIComponent(resource.id)}`, {method: "DELETE"});
      this.resourceMessage = {text: `Resource ${resource.id} deactivated.`, error: false};
      await this.loadResources();
    } catch (error) {
      this.resourceMessage = {text: error.message, error: true};
    } finally {
      this.resourceBusy = false;
    }
  }

  async reactivateResource(resource) {
    this.resourceBusy = true;
    try {
      await this.api.request(`/api/resources/${encodeURIComponent(resource.id)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({active: true}),
      });
      this.resourceMessage = {text: `Resource ${resource.id} reactivated.`, error: false};
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

  async saveOfficePolicy(event) {
    event.preventDefault();
    this.officePolicyBusy = true;
    this.officePolicyMessage = {text: "", error: false};
    const fields = new FormData(event.currentTarget);
    try {
      const policy = await this.api.request(
        `/api/offices/${encodeURIComponent(this.officePolicy.office_id)}/policy`,
        {
          method: "PATCH",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            time_zone: fields.get("time_zone"),
            opens_at: fields.get("opens_at"),
            closes_at: fields.get("closes_at"),
            weekdays: fields.getAll("weekdays").map(Number),
          }),
        },
      );
      this.officePolicy = policy;
      if (this.selected?.office_id === policy.office_id) this.selectedOfficePolicy = policy;
      this.officePolicyMessage = {text: "Office policy updated.", error: false};
    } catch (error) {
      this.officePolicyMessage = {text: error.message, error: true};
    } finally {
      this.officePolicyBusy = false;
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

  changeWorkspace(event) {
    const workspace = event.currentTarget.dataset.workspace;
    if (workspace in WORKSPACES && (workspace !== "facilities" || this.admin)) {
      this.activeWorkspace = workspace;
    }
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
    const workspace = WORKSPACES[this.activeWorkspace];
    return html`
      <a class="skip-link" href="#workspace-content">Skip to workspace</a>
      <div class="workspace-shell">
        <aside class="workspace-sidebar">
          <header class="masthead">
            <div class="wordmark"><span aria-hidden="true">⌑</span><strong>TORI</strong> SPACE</div>
            <p class="desk-label">Workplace atlas <span>/</span> 03</p>
          </header>

          <nav id="workspace-navigation" class="workspace-navigation" aria-label="Workspace">
            <p class="navigation-label">Workspace</p>
            <button
              type="button"
              data-workspace="reserve"
              aria-current=${this.activeWorkspace === "reserve" ? "page" : "false"}
              @click=${this.changeWorkspace}
            ><span>01</span><strong>Reserve space</strong><small>Map and availability</small></button>
            <button
              type="button"
              data-workspace="schedule"
              aria-current=${this.activeWorkspace === "schedule" ? "page" : "false"}
              @click=${this.changeWorkspace}
            ><span>02</span><strong>My schedule</strong><small>Calendar and bookings</small></button>
            <button
              type="button"
              data-workspace="facilities"
              aria-current=${this.activeWorkspace === "facilities" ? "page" : "false"}
              ?hidden=${!this.admin}
              @click=${this.changeWorkspace}
            ><span>03</span><strong>Facilities</strong><small>Spaces and operations</small></button>
          </nav>

          <div class="sidebar-status">
            <span class="signal ${this.offline ? "offline" : ""}" aria-hidden="true"></span>
            <div>
              <small>${this.offline ? "Connection paused" : "Connected workspace"}</small>
              <strong id="identity-text">${this.actor}</strong>
              <span>${this.initialized ? this.tenant : "Checking identity"}</span>
            </div>
          </div>
          <button class="sidebar-signout" id="logout" type="button" ?hidden=${!this.initialized} @click=${this.logout}>Sign out</button>
        </aside>

        <main id="workspace-content" class="workspace-content">
          <header class="workspace-intro" aria-labelledby="page-title">
            <div>
              <p class="eyebrow">${workspace.eyebrow}</p>
              <h1 id="page-title">${workspace.title}</h1>
              <p>${workspace.description}</p>
            </div>
            <dl class="workspace-context" aria-label="Current workspace context">
              <div><dt>Office</dt><dd>Building N</dd></div>
              <div><dt>Floor</dt><dd>Level 03</dd></div>
              <div><dt>Timezone</dt><dd>${this.timeZone}</dd></div>
            </dl>
          </header>

          <section
            id="reserve-workspace"
            class="workspace-view reserve-workspace"
            aria-label="Reserve a workplace resource"
            ?hidden=${this.activeWorkspace !== "reserve"}
          >
            <div class="workspace-toolbar">
              <div><span class="toolbar-kicker">Live floor</span><strong>N.03 workplace plan</strong></div>
              <p>${this.resourcesLoading ? "Loading spaces" : `${this.resources.length} spaces in this view`}</p>
            </div>
            <section class="control-desk" aria-label="Floor plan and selected resource">
              ${floorPlanTemplate(this)}
              <aside class="inspector">
                <p class="eyebrow">Reservation composer</p>
                <div id="selection-empty" class="selection-empty" ?hidden=${Boolean(this.selected)}>
                  <span class="selection-number" aria-hidden="true">01</span>
                  <h2>Start with a space.</h2>
                  <p>Choose a marker on the plan or select a result from the directory below.</p>
                  <ol>
                    <li>Pick a desk or room</li>
                    <li>Set your local time</li>
                    <li>Check and reserve</li>
                  </ol>
                </div>
                <div id="selection" ?hidden=${!this.selected}>
                  <p class="status ${this.availability?.open ? "available" : ""} ${this.availability?.error ? "error" : ""}" id="resource-status" role="status">
                    ${!isBookable(this.selected)
                      ? "Inactive resources cannot be booked"
                      : this.availability?.text ?? "Set a time to check availability"}
                  </p>
                  <div class="resource-title-row">
                    <div>
                      <h2 id="resource-name">${this.selected?.name ?? "—"}</h2>
                      <p id="resource-kind">${this.selected?.kind ?? "—"}</p>
                    </div>
                    <span>${this.selected?.capacity ?? 1} seat${this.selected?.capacity === 1 ? "" : "s"}</span>
                  </div>
                  <dl class="resource-facts">
                    <div><dt>Location</dt><dd>${this.selected?.office_id ?? "—"} / ${this.selected?.floor_id ?? "—"}</dd></div>
                    <div><dt>Capacity</dt><dd id="resource-capacity">${this.selected?.capacity ?? 1}</dd></div>
                    <div><dt>Equipment</dt><dd id="resource-equipment">${this.selected?.equipment?.join(" · ") || "None listed"}</dd></div>
                    <div><dt>Office hours</dt><dd id="resource-office-hours">${this.selectedOfficePolicy
                      ? `${this.selectedOfficePolicy.opens_at}-${this.selectedOfficePolicy.closes_at} ${this.selectedOfficePolicy.time_zone}`
                      : "Loading policy"}</dd></div>
                  </dl>
                  <form id="booking-form" class="booking-form" @submit=${this.requestBooking}>
                    <label>Starts
                      <input
                        id="starts-at"
                        type="datetime-local"
                        required
                        .value=${this.bookingStarts}
                        @input=${(event) => {
                          this.bookingStarts = event.currentTarget.value;
                          this.clearAvailability();
                        }}
                      >
                    </label>
                    <label>Ends
                      <input
                        id="ends-at"
                        type="datetime-local"
                        required
                        .value=${this.bookingEnds}
                        @input=${(event) => {
                          this.bookingEnds = event.currentTarget.value;
                          this.clearAvailability();
                        }}
                      >
                    </label>
                    <button
                      class="secondary-button"
                      id="availability-check"
                      type="button"
                      ?disabled=${this.availabilityBusy || !isBookable(this.selected)}
                      @click=${this.checkAvailability}
                    >${this.availabilityBusy ? "Checking…" : "Check availability"}</button>
                    <button class="action-button" id="booking-submit" type="submit" ?disabled=${this.bookingBusy || !isBookable(this.selected)}>
                      ${this.bookingBusy ? "Reserving…" : "Reserve this time"}
                    </button>
                  </form>
                  <details class="recurrence-panel">
                    <summary>Make it recurring</summary>
                    <form id="recurring-booking-form" @submit=${this.requestRecurringBooking}>
                      <fieldset>
                        <legend>Repeat this interval</legend>
                        <label>Frequency
                          <select id="recurrence" name="recurrence">
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                          </select>
                        </label>
                        <label>Occurrences (2–52)
                          <input id="recurrence-count" name="occurrence_count" type="number" min="2" max="52" value="2" required>
                        </label>
                        <button class="secondary-button" type="submit" ?disabled=${this.recurringBusy || !isBookable(this.selected)}>
                          ${this.recurringBusy ? "Submitting…" : "Book recurring time"}
                        </button>
                      </fieldset>
                    </form>
                  </details>
                </div>
                <p class="response ${this.bookingMessage.error ? "error" : ""}" id="booking-response" role="status">${this.bookingMessage.text}</p>
              </aside>
            </section>

            <section class="list-section" aria-labelledby="resource-list-title">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">Space directory</p>
                  <h2 id="resource-list-title">Find by what you need.</h2>
                </div>
                <p>Filter across location, capacity, equipment, and a precise availability window.</p>
              </div>
              <details class="filter-drawer" open>
                <summary>Search filters</summary>
                <form class="resource-filters" id="resource-filters" @submit=${this.applyResourceFilters}>
                  <label>Office<input id="resource-office-filter" .value=${this.resourceFilters.office_id} @input=${(event) => this.setResourceFilter("office_id", event)}></label>
                  <label>Floor<input id="resource-floor-filter" .value=${this.resourceFilters.floor_id} @input=${(event) => this.setResourceFilter("floor_id", event)}></label>
                  <label>Kind<select id="resource-kind-filter" .value=${this.resourceFilters.kind} @change=${(event) => this.setResourceFilter("kind", event)}><option value="">Any</option><option value="desk">Desk</option><option value="room">Room</option></select></label>
                  <label>Equipment<input id="resource-equipment-filter" placeholder="monitor, screen" .value=${this.resourceFilters.equipment} @input=${(event) => this.setResourceFilter("equipment", event)}></label>
                  <label>Minimum capacity<input id="resource-min-capacity-filter" type="number" min="1" .value=${this.resourceFilters.min_capacity} @input=${(event) => this.setResourceFilter("min_capacity", event)}></label>
                  <label>Available from<input id="availability-from-filter" type="datetime-local" .value=${this.resourceFilters.availability_from} @input=${(event) => this.setResourceFilter("availability_from", event)}></label>
                  <label>Available to<input id="availability-to-filter" type="datetime-local" .value=${this.resourceFilters.availability_to} @input=${(event) => this.setResourceFilter("availability_to", event)}></label>
                  <button class="action-button" type="submit">Apply resource filters</button>
                  <button class="quiet-button" id="clear-resource-filters" type="button" @click=${this.clearResourceFilters}>Clear resource filters</button>
                </form>
              </details>
              <ul id="resource-list" aria-label="Workplace resources">
                ${this.resourcesLoading
                  ? html`<li class="list-message">Loading resources…</li>`
                  : this.resourcesError
                    ? html`<li class="list-message error">Could not load resources: ${this.resourcesError}</li>`
                    : this.resources.length
                      ? this.resources.map((resource) => html`
                          <li class="resource-item ${resource.active === false ? "inactive" : ""}">
                            <button
                              type="button"
                              aria-label=${resource.name ?? resource.id}
                              @click=${() => this.selectResource(resource)}
                            >
                              <span class="resource-kind-badge">${resource.kind ?? "space"}</span>
                              <strong>${resource.name ?? resource.id}</strong>
                              <small>${resource.office_id ?? "—"} / ${resource.floor_id ?? "—"}</small>
                              <span class="resource-capacity">${resource.capacity ?? 1} seat${resource.capacity === 1 ? "" : "s"}</span>
                              <span class="resource-equipment">${resource.equipment?.join(" · ") || "No equipment listed"}${resource.active === false ? " · inactive" : ""}</span>
                            </button>
                          </li>
                        `)
                      : html`<li class="list-message">No resources match this view.</li>`}
              </ul>
              <nav class="resource-pagination" aria-label="Resource pages">
                <button class="secondary-button" type="button" ?disabled=${this.resourceOffset === 0} @click=${this.previousResourcePage}>Previous resources</button>
                <span>Page ${Math.floor(this.resourceOffset / this.resourcePageSize) + 1}</span>
                <button class="secondary-button" type="button" ?disabled=${!this.resourceHasNext} @click=${this.nextResourcePage}>Next resources</button>
              </nav>
            </section>
          </section>

          <section
            id="schedule-workspace"
            class="workspace-view schedule-workspace"
            aria-label="My booking schedule"
            ?hidden=${this.activeWorkspace !== "schedule"}
          >
            ${bookingCalendarTemplate(this)}
            ${bookingListTemplate(this)}
          </section>

          <section
            id="facilities-workspace"
            class="workspace-view facilities-workspace"
            aria-label="Facilities workspace"
            ?hidden=${this.activeWorkspace !== "facilities" || !this.admin}
          >
            ${adminPanelTemplate(this)}
          </section>
        </main>
      </div>

      <footer class="workspace-footer">
        <span>TORI SPACE / LOCAL REFERENCE</span>
        <span id="api-status" role="status">${this.offline
          ? "OFFLINE / CHANGES PAUSED"
          : this.resourcesError
            ? "GATEWAY UNAVAILABLE"
            : this.initialized
              ? "GATEWAY LINKED"
              : "AWAITING GATEWAY"}</span>
        <span>NOT A BUILDING SAFETY SYSTEM</span>
      </footer>
    `;
  }
}
