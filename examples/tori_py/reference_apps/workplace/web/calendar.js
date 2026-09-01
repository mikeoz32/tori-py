export function formatDate(date, timeZone, options = {}) {
  return new Intl.DateTimeFormat(undefined, { timeZone, ...options }).format(date);
}

export function formatRange(start, end, timeZone) {
  return `${formatDate(start, timeZone, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })}-${formatDate(end, timeZone, { hour: "numeric", minute: "2-digit" })}`;
}

function zonedParts(date, timeZone) {
  return Object.fromEntries(
    new Intl.DateTimeFormat("en", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
}

export function calendarDateFromInstant(date, timeZone) {
  const parts = zonedParts(date, timeZone);
  return new Date(Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
  ));
}

export function calendarDateKey(date) {
  return date.toISOString().slice(0, 10);
}

function instantDateKey(date, timeZone) {
  const parts = zonedParts(date, timeZone);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function calendarFirstDate(calendarDate, view) {
  const first = new Date(calendarDate);
  if (view === "week") {
    first.setUTCDate(first.getUTCDate() - ((first.getUTCDay() + 6) % 7));
  }
  return first;
}

export function bookingTouchesDay(booking, key, timeZone) {
  const end = new Date(booking.ends_at).getTime();
  if (!Number.isFinite(end)) return false;
  return instantDateKey(new Date(booking.starts_at), timeZone) <= key
    && instantDateKey(new Date(end - 1), timeZone) >= key;
}

export function bookingQuery(calendarDate, view) {
  const first = calendarFirstDate(calendarDate, view);
  const days = view === "week" ? 7 : 1;
  const starts = new Date(first);
  const ends = new Date(first);
  // The padding covers every IANA offset; rendering applies exact local-day filtering.
  starts.setUTCDate(starts.getUTCDate() - 1);
  ends.setUTCDate(ends.getUTCDate() + days + 1);
  return new URLSearchParams({
    starts_at: starts.toISOString(),
    ends_at: ends.toISOString(),
  });
}

export function localDateTimeValue(date) {
  const local = new Date(date);
  local.setMinutes(local.getMinutes() - local.getTimezoneOffset());
  return local.toISOString().slice(0, 16);
}
