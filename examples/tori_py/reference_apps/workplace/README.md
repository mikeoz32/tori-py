# Tori Space workplace reference application

Tori Space is a small, standalone workplace-reservation reference application.
It is independent of the rest of the examples at runtime and is **not
affiliated with Artishok or any vendor**. Names, copy, design, and assets in
this directory are original to this demo.

## Architecture

```text
browser (/web) ── Authorization Code + PKCE ──> Keycloak 26.7.3
       │ Bearer token
       v
api-gateway (:8010) ──> spaces / bookings / notifications
       │                         │
       ├── validates issuer, audience, tenant_id and roles
       └── PostgreSQL databases + RabbitMQ durable messages
```

`spaces`, `bookings`, and `notifications` are separately deployed application
processes with their own PostgreSQL database and role. `api-gateway` is the
only process published to the browser; it also serves the web directory and
the verified Keycloak browser module at `/assets/keycloak.js` and the verified
Lit runtime at `/assets/lit-core.min.js`. RabbitMQ is the asynchronous
integration boundary. Keycloak owns identity and browser login; the API owns
authorization decisions and resource data.

## Run locally

Prerequisites: Docker Compose and `uv`. From this directory:

```sh
docker compose -f compose.yaml up --build
```

Open:

- Web: http://localhost:8010/web/
- API gateway: http://localhost:8010/api/
- Keycloak admin: http://localhost:8080/admin/ (admin / `keycloak-admin-demo-only`)
- RabbitMQ management: http://localhost:15672/ (`rabbitmq_demo` / `rabbitmq-demo-only`)

All exposed ports bind only to `localhost`/`127.0.0.1`. Delete local demo state
with `docker compose -f compose.yaml down -v`.

With the stack healthy, exercise real PKCE login, RPC, booking idempotency,
outbox delivery, and tenant isolation from the repository root:

```sh
uv run --no-sync python -m examples.tori_py.reference_apps.workplace.smoke
```

The Compose migration jobs invoke their dedicated migration modules through
`uv` before starting their corresponding process. Compose is also responsible
for placing the verified `keycloak.js` adapter in the gateway image, so these
instructions intentionally do not advertise unsupported host process commands.

RabbitMQ creates its application users after its health check. `rabbitmq_demo`
is the local management/setup administrator; it is not supplied to an
application process. The local-only application credentials are:

| Process | Username | Password |
| --- | --- | --- |
| API gateway | `gateway_demo` | `gateway-demo-only` |
| Spaces | `spaces_demo` | `spaces-demo-only` |
| Bookings | `bookings_demo` | `bookings-demo-only` |
| Notifications | `notifications_demo` | `notifications-demo-only` |

The browser provides day/week calendar views in a selectable IANA timezone and
loads the displayed interval through bounded booking pages. Bookings remain UTC
on the wire and in storage. Facilities administrators also receive tenant-scoped
lifecycle counts, outbox diagnostics and cleanup, and an immutable booking audit
trail.

## Demo identities

These are deliberately weak, local-only, **demo-only** passwords embedded in
the startup realm import. Never copy them into a deployed realm.

| Tenant | Role | Username | Password |
| --- | --- | --- | --- |
| `tenant-north` | employee | `north.employee` | `north-employee-demo-only` |
| `tenant-north` | facilities admin | `north.admin` | `north-admin-demo-only` |
| `tenant-south` | employee | `south.employee` | `south-employee-demo-only` |
| `tenant-south` | facilities admin | `south.admin` | `south-admin-demo-only` |

The `tenant_id` user attribute is mapped to an access-token claim. Roles are
client roles on `tori-space-web`: `employee` and `facilities-admin`. The web client is public,
permits **Standard Flow only**, and has exact local redirect/web-origin entries
for `http://localhost:8010` and `http://127.0.0.1:8010`. It requests the
`tori-space-api` audience through a dedicated client scope.

The native web demo imports `/assets/keycloak.js`, initializes with
`login-required`, `flow: "standard"`, and `pkceMethod: "S256"`. It keeps
adapter tokens in memory, refreshes before every API request, and attaches the
access token as a bearer token. It deliberately does not put tokens in local
storage, session storage, a cookie, or the URL.

The no-build browser client uses a light-DOM Lit custom element as its reactive
root. Authentication, API access, calendar calculations, the floor plan,
booking views, and facilities controls remain separate ES modules under
`web/`. Light DOM intentionally keeps the existing global stylesheet and
accessibility selectors effective. The gateway serves only an explicit
allowlist of those modules and generated vendor assets.

Official references:

- [Keycloak JavaScript adapter](https://www.keycloak.org/securing-apps/javascript-adapter)
- [Keycloak realm import/export](https://www.keycloak.org/server/importExport)
- [Keycloak downloads](https://www.keycloak.org/downloads)
- [Lit bundles](https://lit.dev/docs/getting-started/#use-bundles)
- [Lit production guidance](https://lit.dev/docs/tools/production/#preparing-code-for-production)

### Installing keycloak-js without npm or a CDN

This demo has no Node or npm build and does not use a CDN. The Dockerfile
downloads the official Keycloak **26.2.4** adapter release pinned in
[`keycloak-js.manifest`](./keycloak-js.manifest), verifies its SHA-256 digest,
and extracts `package/lib/keycloak.js` into the image. The gateway exposes only
that generated file at `/assets/keycloak.js`; it is not committed to the repo.

### Installing Lit without npm or a runtime CDN

This demo also downloads the official Lit **3.3.1** production bundle during
the Docker build. [`lit-js.manifest`](./lit-js.manifest) records the pinned URL
and SHA-256 digest checked by the Dockerfile. The verified file is generated at
`web/assets/lit-core.min.js` in the image and served from the same origin; the
browser never contacts a public CDN.

To upgrade Lit, choose an official `lit/dist` release, calculate the SHA-256 of
its `core/lit-core.min.js` bundle, update the version, URL, and digest in both
the manifest and Dockerfile, then rebuild the image and run the browser test.
No npm install or JavaScript compilation step is involved.

## Trust boundaries and delivery semantics

- The browser is untrusted. It receives only short-lived tokens and sends
  requests to the gateway; client-side role checks only control presentation.
- The gateway verifies signature, issuer, expiration, `aud` containing
  `tori-space-api`, `tenant_id`, and required role on every protected request.
  It creates the `Principal` carried over RPC; services validate its workplace
  role and derive tenant and actor from it, not request body, UI state, routing,
   or a user-supplied header. The broker is an internal boundary, not a trust
   bypass: each process has a separate RabbitMQ credential limited to its own
   topology resources and routing keys. The setup/management administrator is
   reserved for local setup and the management UI.
- Every database read and write must be constrained by `tenant_id`; resource
  identifiers alone are not authorization. Separate databases/roles limit
  accidental cross-service access but do not replace row-level tenant checks.
- RabbitMQ delivery and RPC/event handling are **at least once**. The outbox
  uses database lease claims so replicas do not normally publish the same row
  concurrently. Lease recovery and the inbox/idempotency patterns reduce
  duplicate effects but do not give exactly-once end-to-end delivery. Consumers
  must be idempotent, and the application must handle duplicated or delayed
  notifications.

## Tests and non-goals

Run the reference-app unit and security specifications from the repository root
with `uv`:

```sh
uv run pytest examples/tori_py/reference_apps/workplace/test_workplace.py examples/tori_py/reference_apps/workplace/tests
```

The PostgreSQL concurrency specification uses `pytest-docker` and requires the
Linux-only `psycopg` dependency from this workspace. It verifies that the real
exclusion constraint commits exactly one of two overlapping reservations while
keeping booking, outbox, and audit rows atomic.

This is a reference, not a production deployment template. Non-goals include
real building access control, calendar-provider synchronization, production
secrets management, TLS termination, backups/HA, automatic migrations in a
running production system, regulatory audit retention, and exactly-once
messaging. The floor plan is illustrative and must not be used for emergency,
safety, or occupancy decisions.
