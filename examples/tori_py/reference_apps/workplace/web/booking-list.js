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
                        <button class="secondary-button" type="button" @click=${() => host.bookingAction(booking, "check-in")}>
                          Check in
                        </button>
                        <button class="secondary-button" type="button" @click=${() => host.beginReschedule(booking)}>
                          Reschedule
                        </button>
                        ${booking.series_id ? html`
                          <button class="secondary-button" type="button" ?disabled=${host.cancellationBusy} @click=${() => host.cancelBooking(booking, "one")}>
                            Cancel this occurrence
                          </button>
                          <button class="secondary-button" type="button" ?disabled=${host.cancellationBusy} @click=${() => host.cancelBooking(booking, "this-and-following")}>
                            Cancel this and following
                          </button>
                          <button class="secondary-button" type="button" ?disabled=${host.cancellationBusy} @click=${() => host.cancelBooking(booking, "entire-series")}>
                            Cancel entire series
                          </button>
                        ` : html`
                          <button class="secondary-button" type="button" ?disabled=${host.cancellationBusy} @click=${() => host.cancelBooking(booking, "one")}>
                            Cancel booking
                          </button>
                        `}
                      ` : ""}
                    </div>
                  </article>
                `)
              : html`<p class="list-message">No bookings are recorded for this interval.</p>`}
      </div>
      ${host.rescheduling ? html`
        <form class="reschedule-form" id="reschedule-form" @submit=${host.saveReschedule}>
          <h3>Reschedule ${host.rescheduling.id}</h3>
          <label>
            Start (browser local time)
            <input
              id="reschedule-starts-at"
              type="datetime-local"
              required
              .value=${host.rescheduleStarts}
              @input=${(event) => {
                host.rescheduleStarts = event.currentTarget.value;
              }}
            >
          </label>
          <label>
            End (browser local time)
            <input
              id="reschedule-ends-at"
              type="datetime-local"
              required
              .value=${host.rescheduleEnds}
              @input=${(event) => {
                host.rescheduleEnds = event.currentTarget.value;
              }}
            >
          </label>
          <button class="action-button" type="submit" ?disabled=${host.rescheduleBusy}>
            ${host.rescheduleBusy ? "Saving…" : "Save reschedule"}
          </button>
          <button class="quiet-button" type="button" @click=${host.cancelReschedule}>Dismiss</button>
        </form>
      ` : ""}
      <p class="response ${host.bookingsMessage.error ? "error" : ""}" id="bookings-response" role="status">${host.bookingsMessage.text}</p>
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
