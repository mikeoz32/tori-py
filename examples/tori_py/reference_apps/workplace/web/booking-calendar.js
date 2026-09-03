import {html} from "/assets/lit-core.min.js";

import {
  bookingResourceName,
  bookingTouchesDay,
  calendarDateKey,
  calendarFirstDate,
  formatDate,
  formatRange,
} from "/web/calendar.js";

function dayTemplate(host, day) {
  const key = calendarDateKey(day);
  const rows = host.bookings.filter(
    (booking) => bookingTouchesDay(booking, key, host.timeZone),
  );
  return html`
    <section class="calendar-day">
      <h3>${formatDate(day, "UTC", {
        weekday: "short",
        month: "short",
        day: "numeric",
      })}</h3>
      ${rows.length
        ? rows.map((booking) => html`
            <div class="calendar-entry">
              <strong>${bookingResourceName(booking, host.resources)}</strong>
              <span>${formatRange(
                new Date(booking.starts_at),
                new Date(booking.ends_at),
                host.timeZone,
              )}</span>
              <small>${booking.status ?? "booked"}</small>
            </div>
          `)
        : html`<p class="empty-state">No bookings</p>`}
    </section>
  `;
}

export function bookingCalendarTemplate(host) {
  const first = calendarFirstDate(host.calendarDate, host.calendarView);
  const days = host.calendarView === "week" ? 7 : 1;
  const dates = Array.from({length: days}, (_, index) => {
    const day = new Date(first);
    day.setUTCDate(day.getUTCDate() + index);
    return day;
  });
  const last = dates.at(-1);
  const range = `${formatDate(first, "UTC", {
    month: "long",
    day: "numeric",
    year: "numeric",
  })}${days > 1 ? ` - ${formatDate(last, "UTC", {
    month: "long",
    day: "numeric",
    year: "numeric",
  })}` : ""} / ${host.timeZone}`;

  return html`
    <section class="calendar-section" aria-labelledby="calendar-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Calendar</p>
          <h2 id="calendar-title">Week at a glance</h2>
        </div>
        <div class="calendar-tools">
          <label>View
            <select id="calendar-view" .value=${host.calendarView} @change=${host.changeCalendarView}>
              <option value="day">Day</option>
              <option value="week">Week</option>
            </select>
          </label>
          <label>Display timezone
            <select
              id="timezone"
              aria-label="Calendar display timezone"
              .value=${host.timeZone}
              @change=${host.changeTimeZone}
            >
              ${host.timeZones.map((zone) => html`<option value=${zone}>${zone}</option>`)}
            </select>
          </label>
          <button class="secondary-button" id="calendar-prev" type="button" aria-label="Previous period" @click=${host.previousPeriod}>←</button>
          <button class="secondary-button" id="calendar-today" type="button" @click=${host.today}>Today</button>
          <button class="secondary-button" id="calendar-next" type="button" aria-label="Next period" @click=${host.nextPeriod}>→</button>
        </div>
      </div>
      <p id="calendar-range" class="calendar-range">${range}</p>
      <div id="calendar" class="calendar" aria-live="polite">
        ${host.bookingsLoading
          ? html`<p class="list-message">Loading bookings...</p>`
          : host.bookingsError
            ? html`<p class="list-message error">Calendar unavailable. Retry when the gateway is reachable.</p>`
            : dates.map((day) => dayTemplate(host, day))}
      </div>
      <button
        class="secondary-button retry"
        id="bookings-retry"
        type="button"
        ?hidden=${!host.bookingsError}
        @click=${host.loadBookings}
      >Retry calendar</button>
    </section>
  `;
}
