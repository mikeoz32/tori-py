import {html, nothing} from "/assets/lit-core.min.js";

import {formatDate} from "/web/calendar.js";

function metric(label, value) {
  return html`<div><dt>${label}</dt><dd>${String(value ?? "-")}</dd></div>`;
}

export function adminPanelTemplate(host) {
  if (!host.admin) return nothing;
  const dashboard = host.dashboard;
  const diagnostics = host.diagnostics;

  return html`
    <section class="admin-panel" id="admin-panel" aria-labelledby="admin-title">
      <div class="section-heading admin-heading">
        <div>
          <p class="eyebrow">Today at a glance</p>
          <h2 id="admin-title">Facilities overview</h2>
        </div>
        <button class="secondary-button" id="admin-retry" type="button" @click=${host.loadAdmin}>Refresh ledger</button>
      </div>
      <div id="dashboard-metrics" class="metrics" aria-live="polite">
        ${host.adminLoading
          ? html`<p class="list-message">Loading facilities overview...</p>`
          : host.adminError
            ? html`<p class="list-message error">Facilities dashboard unavailable: ${host.adminError}</p>`
            : html`
                ${metric("Active bookings", dashboard?.active_bookings)}
                ${metric("No-shows", dashboard?.no_shows)}
                ${metric("Events pending", dashboard?.outbox_pending)}
                ${metric("Delivery failures", dashboard?.outbox_failures)}
              `}
      </div>
      <div class="admin-workbench">
        <section class="admin-card policy-card" aria-labelledby="policy-title">
          <div class="card-heading">
            <div><span>01 / Access</span><h3 id="policy-title">Office policy</h3></div>
            <p>Set the local hours people can reserve.</p>
          </div>
          <div class="policy-office-picker">
            <label>Office ID
              <input id="policy-office-id" .value=${host.policyOfficeId} @input=${host.setPolicyOffice} required>
            </label>
            <button class="secondary-button" type="button" @click=${host.loadAdminOfficePolicy} ?disabled=${host.officePolicyBusy}>
              Load policy
            </button>
          </div>
          ${host.officePolicy ? html`
            <form id="office-policy-form" @submit=${host.saveOfficePolicy}>
              <label>Time zone
                <select name="time_zone" .value=${host.officePolicy.time_zone}>
                  ${host.timeZones.map((zone) => html`<option value=${zone}>${zone}</option>`)}
                </select>
              </label>
              <div class="policy-hours">
                <label>Opens at<input name="opens_at" type="time" .value=${host.officePolicy.opens_at} required></label>
                <label>Closes at<input name="closes_at" type="time" .value=${host.officePolicy.closes_at} required></label>
              </div>
              <fieldset>
                <legend>Working days</legend>
                ${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((label, day) => html`
                  <label><input name="weekdays" type="checkbox" value=${day} .checked=${host.officePolicy.weekdays.includes(day)}><span>${label.slice(0, 2)}</span></label>
                `)}
              </fieldset>
              <button class="action-button" type="submit" ?disabled=${host.officePolicyBusy}>
                ${host.officePolicyBusy ? "Saving..." : "Save office policy"}
              </button>
            </form>
          ` : html`<p class="list-message">Office policy unavailable.</p>`}
          <p class="response ${host.officePolicyMessage.error ? "error" : ""}" id="office-policy-response" role="status">${host.officePolicyMessage.text}</p>
        </section>

        <section class="admin-card delivery-card" aria-labelledby="delivery-title">
          <div class="card-heading">
            <div><span>02 / Delivery</span><h3 id="delivery-title">Event delivery</h3></div>
            <p>Operational details for persistent messages.</p>
          </div>
          <div id="outbox-metrics" class="metrics compact" aria-live="polite">
            ${host.adminLoading
              ? html`<p class="list-message">Loading delivery health...</p>`
              : host.adminError
                ? html`<p class="list-message error">Delivery health unavailable.</p>`
                : html`
                    ${metric("Pending", diagnostics?.pending)}
                    ${metric("Dead letter", diagnostics?.dead_letter)}
                    ${metric("Failures", diagnostics?.failures)}
                    ${metric("Lag", diagnostics?.lag_seconds == null ? "-" : `${diagnostics.lag_seconds}s`)}
                  `}
          </div>
          <form id="outbox-cleanup-form" @submit=${host.cleanupOutbox}>
            <label>Remove delivered records before
              <input
                id="outbox-cleanup-before"
                type="datetime-local"
                .value=${host.cleanupBefore}
                @input=${(event) => {
                  host.cleanupBefore = event.currentTarget.value;
                }}
                required
              >
            </label>
            <button class="secondary-button" id="outbox-cleanup-submit" type="submit" ?disabled=${host.cleanupBusy}>
              ${host.cleanupBusy ? "Cleaning..." : "Clean delivered outbox records"}
            </button>
          </form>
          <p class="response ${host.outboxMessage.error ? "error" : ""}" id="outbox-response" role="status">${host.outboxMessage.text}</p>
        </section>

        <section class="admin-card audit-card" aria-labelledby="audit-title">
          <div class="card-heading">
            <div><span>03 / Record</span><h3 id="audit-title">Audit trail</h3></div>
            <p>An immutable history of booking changes.</p>
          </div>
          <div id="audit-log" class="audit-log" aria-live="polite">
            ${host.adminLoading
              ? html`<p class="list-message">Loading audit trail...</p>`
              : host.adminError
                ? html`<p class="list-message error">Audit trail unavailable.</p>`
                : host.auditEntries.length
                  ? host.auditEntries.map((entry) => html`
                      <article class="audit-row">
                        <strong>${entry.action ?? "Booking transition"}</strong>
                        <span>Resource ${entry.resource_id ?? "-"} / booking ${entry.booking_id ?? "-"}</span>
                        <p>${entry.from_status ?? "-"} -&gt; ${entry.to_status ?? "-"}</p>
                        <small>${entry.actor_id ?? "-"} / ${entry.occurred_at
                          ? formatDate(new Date(entry.occurred_at), host.timeZone, {
                              dateStyle: "medium",
                              timeStyle: "short",
                            })
                          : "-"}</small>
                      </article>
                    `)
                  : html`<p class="empty-state">No audit records.</p>`}
          </div>
        </section>
      </div>

      <section class="resource-management" aria-labelledby="resources-admin-title">
        <div class="section-heading">
          <div><p class="eyebrow">Space inventory</p><h2 id="resources-admin-title">Resource management</h2></div>
          <p>Create a space, then maintain its location, equipment, and availability.</p>
        </div>
        <div class="resource-management-grid">
          <section class="admin-card resource-create-card">
            <div class="card-heading"><div><span>New</span><h3>Add a resource</h3></div></div>
            <form id="resource-form" @submit=${host.createResource}>
              <label>Office<input name="office_id" value="building-n" required></label>
              <label>Floor<input name="floor_id" value="level-03" required></label>
              <label>Name<input name="name" required></label>
              <label>Kind
                <select name="kind"><option value="desk">Desk</option><option value="room">Room</option></select>
              </label>
              <label>Map X<input name="x" type="number" min="0" max="1000" required></label>
              <label>Map Y<input name="y" type="number" min="0" max="1000" required></label>
              <label>Equipment<input name="equipment" placeholder="monitor, power"></label>
              <label>Capacity<input name="capacity" type="number" min="1" max="1000" value="1" required></label>
              <button class="action-button" type="submit" ?disabled=${host.resourceBusy}>
                ${host.resourceBusy ? "Registering..." : "Register resource"}
              </button>
            </form>
            <p class="response ${host.resourceMessage.error ? "error" : ""}" id="resource-response" role="status">${host.resourceMessage.text}</p>
          </section>

          <div class="resource-controls" aria-live="polite">
            ${host.resources.map((resource) => html`
              <details class="resource-control ${resource.active === false ? "inactive" : ""}">
                <summary>
                  <span><strong>${resource.name}</strong><small>${resource.kind ?? "space"} / ${resource.capacity ?? 1} seats</small></span>
                  <em>${resource.active === false ? "Inactive" : "Active"}</em>
                </summary>
                <form @submit=${(event) => host.updateResource(event, resource)}>
                  <label>Name<input id=${`resource-edit-name-${resource.id}`} name="name" .value=${resource.name ?? ""} required></label>
                  <label>Office<input id=${`resource-edit-office-${resource.id}`} name="office_id" .value=${resource.office_id ?? ""} required></label>
                  <label>Floor<input id=${`resource-edit-floor-${resource.id}`} name="floor_id" .value=${resource.floor_id ?? ""} required></label>
                  <label>Kind
                    <select id=${`resource-edit-kind-${resource.id}`} name="kind" .value=${resource.kind ?? "desk"}>
                      <option value="desk">Desk</option><option value="room">Room</option>
                    </select>
                  </label>
                  <label>Map X<input id=${`resource-edit-x-${resource.id}`} name="x" type="number" min="0" max="1000" .value=${String(resource.x ?? 0)} required></label>
                  <label>Map Y<input id=${`resource-edit-y-${resource.id}`} name="y" type="number" min="0" max="1000" .value=${String(resource.y ?? 0)} required></label>
                  <label>Equipment<input name="equipment" .value=${resource.equipment?.join(", ") ?? ""}></label>
                  <label>Capacity<input name="capacity" type="number" min="1" max="1000" .value=${String(resource.capacity ?? 1)} required></label>
                  <button class="secondary-button" type="submit" ?disabled=${host.resourceBusy}>Save ${resource.name}</button>
                </form>
                ${resource.active === false
                  ? html`<button class="action-button" type="button" ?disabled=${host.resourceBusy} @click=${() => host.reactivateResource(resource)}>Reactivate ${resource.name}</button>`
                  : html`<button class="quiet-button" type="button" ?disabled=${host.resourceBusy} @click=${() => host.deactivateResource(resource)}>Deactivate ${resource.name}</button>`}
              </details>
            `)}
          </div>
        </div>
      </section>
    </section>
  `;
}
