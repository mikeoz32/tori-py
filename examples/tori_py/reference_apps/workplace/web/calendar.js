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

export function bookingResourceName(booking, resources) {
  return booking.resource_name
    ?? resources.find((resource) => resource.id === booking.resource_id)?.name
    ?? booking.resource_id
    ?? "Resource";
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

const WEEKDAY_INDEX = Object.freeze({
  Mon: 0,
  Tue: 1,
  Wed: 2,
  Thu: 3,
  Fri: 4,
  Sat: 5,
  Sun: 6,
});

function zonedTimeParts(date, timeZone) {
  return Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
}

function minutesFromTime(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

export function nextPolicyInterval(policy, now = new Date()) {
  const opensAt = minutesFromTime(policy.opens_at);
  const closesAt = minutesFromTime(policy.closes_at);
  const duration = Math.min(60, closesAt - opensAt);
  const step = 15 * 60 * 1000;
  const earliest = now.getTime() + 60 * 60 * 1000;
  const candidate = new Date(Math.ceil(earliest / step) * step);

  for (let index = 0; index < 14 * 24 * 4; index += 1) {
    const startsAt = new Date(candidate.getTime() + index * step);
    const endsAt = new Date(startsAt.getTime() + duration * 60 * 1000);
    const start = zonedTimeParts(startsAt, policy.time_zone);
    const end = zonedTimeParts(endsAt, policy.time_zone);
    const sameDay = start.year === end.year
      && start.month === end.month
      && start.day === end.day;
    const startMinute = Number(start.hour) * 60 + Number(start.minute);
    const endMinute = Number(end.hour) * 60 + Number(end.minute);

    if (sameDay
      && policy.weekdays.includes(WEEKDAY_INDEX[start.weekday])
      && startMinute >= opensAt
      && endMinute <= closesAt) {
      return {startsAt, endsAt};
    }
  }
  throw new Error("Office policy has no bookable interval in the next two weeks.");
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
