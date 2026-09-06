# Tori Space UX implementation plan

## Product direction

Tori Space is a facilities platform with two role-specific applications that
share identity, API, and visual foundations:

- `/live/workplace` is the employee application for reserving a space and
  managing personal bookings.
- `/live/facilities` is the facilities-administrator application for workplace
  operations.
- `/web/` remains the standalone employee application used by the no-build
  reference client.

The existing editorial workplace-atlas character remains, but navigation,
headings, and controls prioritize operational clarity over decoration.

## Employee application

The primary flow is `time -> available spaces -> selection -> confirmation`.
Date and time are chosen before a resource. Applying that interval loads only
available resources through the existing resource endpoint. Advanced location,
kind, equipment, and capacity constraints remain progressively disclosed.

Desktop presents a synchronized result list and floor plan. Selecting a result
in either surface updates the other surface and opens one booking panel. On
320-390 px screens, the list is the initial surface and Map is an adjacent tab.
The selection and interval survive switching between those views.

`My schedule` remains a separate employee section. Recurrence, rescheduling,
and series cancellation are secondary actions rather than peers of the primary
booking flow.

## Facilities application

Facilities administrators enter at Overview. The application has five peer
sections:

1. Overview: issues and exceptions that require attention, supported by compact
   contextual metrics.
2. Spaces: inventory, activation state, resource editing, and map placement.
3. Policies: office timezone, opening interval, and working days.
4. Audit: immutable booking transitions.
5. System health: outbox delivery diagnostics and cleanup.

The current APIs provide aggregate no-show and delivery counts, resource
records, audit records, policy state, and outbox diagnostics. Overview may link
an aggregate exception to the relevant section, but it must not invent
record-level issue details.

## API feature request

The following is intentionally deferred and must be implemented as a separate
backend feature before the UI presents a record-level action queue:

- A tenant-scoped, facilities-admin-only issue feed with stable pagination.
- Typed issue category and severity for no-shows, inactive resources, policy
  conflicts, dead letters, and retrying deliveries.
- Stable entity identifiers, occurrence timestamps, and enough context to open
  the corresponding resource, booking, audit entry, or delivery record.
- Explicit resolved/open semantics; aggregate dashboard counts are not a
  substitute for issue records.

## Technical diagnostics

LiveView connection state, gateway state, and reference-application details
belong in a collapsed developer drawer. They must not occupy the primary task
hierarchy. The safety disclaimer remains available there and in documentation.

## Acceptance criteria

- Employee and facilities LiveView routes mount distinct custom elements.
- A non-admin cannot use the facilities application or facilities APIs.
- Facilities navigation does not appear in the employee application.
- Facilities Overview, Spaces, Policies, Audit, and System health are distinct
  views rather than one long workbench.
- Employee resource requests include the selected availability interval before
  results are presented as available.
- Desktop list and map selection remain synchronized.
- Mobile defaults to List and exposes Map without document-level overflow.
- Advanced filters, recurrence, and developer diagnostics use progressive
  disclosure.
- Existing authentication, PKCE, bearer-token, idempotency, tenant isolation,
  and LiveView/Lit ownership boundaries remain unchanged.
