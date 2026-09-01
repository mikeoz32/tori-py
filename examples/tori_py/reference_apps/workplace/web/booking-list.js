import {html} from "/assets/lit-core.min.js";

import {formatRange} from "/web/calendar.js";

export function bookingListTemplate(host) {
  return html`
    <section class="bookings-section" aria-labelledby="bookings-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Your schedule</p>
          <h2 id="bookings-title">Bookings ledger</h2>
        </div>
        <button class="secondary-button" id="bookings-refresh" type="button" @click=${host.loadBookings}>Refresh bookings</button>
      </div>
      <div class="bookings-list" aria-live="polite">
        ${host.bookingsLoading
          ? html`<p class="list-message">Loading bookings...</p>`
          : host.bookingsError
            ? html`<p class="list-message error">Could not load bookings: ${host.bookingsError}</p>`
            : host.bookings.length
              ? host.bookings.map((booking) => html`
                  <article class="booking-row">
                    <div>
                      <h3>${booking.resource_name ?? booking.resource_id ?? "Resource"}</h3>
                      <p>${formatRange(
                        new Date(booking.starts_at),
                        new Date(booking.ends_at),
                        host.timeZone,
                      )}</p>
                      <small>Status: ${booking.status ?? "unknown"}</small>
                    </div>
                    <div class="booking-actions">
                      ${booking.status === "booked" ? html`
                        <button class="secondary-button" type="button" @click=${() => host.bookingAction(booking, "check-in")}>Check in</button>
                        <button class="secondary-button" type="button" @click=${() => host.bookingAction(booking, "cancel", true)}>Cancel</button>
                      ` : ""}
                    </div>
                  </article>
                `)
              : html`<p class="list-message">No bookings are recorded for this interval.</p>`}
      </div>
      <button
        class="secondary-button retry"
        id="bookings-list-retry"
        type="button"
        ?hidden=${!host.bookingsError}
        @click=${host.loadBookings}
      >Retry bookings</button>
    </section>
  `;
}
