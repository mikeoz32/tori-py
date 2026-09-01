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
      <p class="eyebrow">Facilities only</p>
      <h3 id="admin-title">Operations ledger</h3>
      <div id="dashboard-metrics" class="metrics" aria-live="polite">
        ${host.adminLoading
          ? html`<p class="list-message">Loading facilities ledger...</p>`
          : host.adminError
            ? html`<p class="list-message error">Facilities dashboard unavailable: ${host.adminError}</p>`
            : html`
                ${metric("Active", dashboard?.active_bookings)}
                ${metric("No shows", dashboard?.no_shows)}
                ${metric("Outbox pending", dashboard?.outbox_pending)}
                ${metric("Dead letter", dashboard?.outbox_dead_letter)}
                ${metric("Outbox failures", dashboard?.outbox_failures)}
                ${metric("Outbox lag", dashboard?.outbox_lag_seconds == null ? "-" : `${dashboard.outbox_lag_seconds}s`)}
              `}
      </div>
      <h3>Outbox diagnostics</h3>
      <div id="outbox-metrics" class="metrics" aria-live="polite">
        ${host.adminLoading
          ? html`<p class="list-message">Loading outbox diagnostics...</p>`
          : host.adminError
            ? html`<p class="list-message error">Outbox diagnostics unavailable.</p>`
            : html`
                ${metric("Pending", diagnostics?.pending)}
                ${metric("Dead letter", diagnostics?.dead_letter)}
                ${metric("Failures", diagnostics?.failures)}
                ${metric("Lag", diagnostics?.lag_seconds == null ? "-" : `${diagnostics.lag_seconds}s`)}
              `}
      </div>
      <form id="outbox-cleanup-form" @submit=${host.cleanupOutbox}>
        <label>Cleanup before (browser local time)
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
      <button class="secondary-button" id="admin-retry" type="button" @click=${host.loadAdmin}>Refresh ledger</button>
      <h3>Immutable audit trail</h3>
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
      <h3>Add a resource</h3>
      <form id="resource-form" @submit=${host.createResource}>
        <input type="hidden" name="office_id" value="building-n">
        <input type="hidden" name="floor_id" value="level-03">
        <label>Name<input name="name" required></label>
        <label>Kind
          <select name="kind">
            <option value="desk">Desk</option>
            <option value="room">Room</option>
          </select>
        </label>
        <label>Map X<input name="x" type="number" min="0" max="1000" required></label>
        <label>Map Y<input name="y" type="number" min="0" max="1000" required></label>
        <button class="action-button" type="submit" ?disabled=${host.resourceBusy}>
          ${host.resourceBusy ? "Registering..." : "Register resource"}
        </button>
      </form>
      <p class="response ${host.resourceMessage.error ? "error" : ""}" id="resource-response" role="status">${host.resourceMessage.text}</p>
    </section>
  `;
}
