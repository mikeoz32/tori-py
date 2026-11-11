# Configuration and Security

`LiveViewOptions` is a frozen dataclass validated on construction. Invalid
values raise `LiveViewConfigurationError` before the application starts.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `secret` | required | HMAC key for mount tokens; at least 32 UTF-8 bytes; hidden from `repr()` |
| `socket_path` | `/_tori/live` | Phoenix endpoint base; the WebSocket route is `{socket_path}/websocket` |
| `client_path` | `/_tori/live.js` | Route serving the bundled Phoenix clients and bootstrap |
| `allowed_origins` | `()` | Explicit browser origins; empty means "same origin as the `Host` header" |
| `max_message_bytes` | `65_536` | Largest inbound text frame, checked before JSON decoding |
| `token_max_age_ms` | `86_400_000` | Mount token lifetime (24 hours) |
| `join_timeout_seconds` | `10.0` | Time allowed for the first join after the socket opens |
| `idle_timeout_seconds` | `75.0` | Time allowed between inbound frames once joined |
| `redirect_hosts` | `()` | Extra bare host names that `redirect()` may target |

Paths must start with one `/`, must not be `/` or end with `/`, carry no query
or fragment, and must differ from each other and from every page path. Integer
limits must be positive integers, timeouts positive finite numbers, and
`allowed_origins` and `redirect_hosts` tuples.

## Provide the Secret from Configuration

`LiveViewModule.for_root()` takes a concrete options value, so read the secret
before the module is composed, for example from the environment:

```python
import os

from tori_py_liveview import LiveViewModule, LiveViewOptions

liveview_module = LiveViewModule.for_root(
    LiveViewOptions(
        secret=os.environ["TORI_LIVEVIEW_SECRET"],
        allowed_origins=("https://app.example.com",),
    ),
    pages=[TasksLive],
)
```

Generate a strong value once and store it in your secret manager:

```text
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Every replica serving the same pages needs the same secret: the HTTP render and
the WebSocket join of one page may reach different processes.

## Mount Tokens

The HTTP render embeds a signed token in the live root. It carries the page
identity, route action, session name, path parameters, resource (path and
query), and issue time, encoded as URL-safe Base64 JSON with an HMAC-SHA256
signature. On join, the server verifies the signature in constant time, checks
the age, and requires that the join URL still matches the signed route.

Tokens provide integrity and expiry only:

- They are readable by anyone who sees the page. Do not put secrets in paths or
  query strings.
- They do not authenticate the visitor or authorize the page. Run access checks
  in [mount hooks](navigation.md#authorization).
- They can be replayed until they expire.

An invalid, stale, or expired token receives a join error with reason
`unauthorized`. The official client then reloads the page, which issues a fresh
token. Pages left open longer than `token_max_age_ms` therefore reload on their
next reconnect, and rotating the secret reloads open pages the same way.

## Origin Checks

Browsers do not apply CORS to WebSockets, so the gateway checks the `Origin`
header before accepting the socket. A missing, repeated, or malformed origin is
rejected with close code `1008`.

With empty `allowed_origins`, the origin must equal the WebSocket scheme and
`Host` header (`ws` maps to `http`, `wss` to `https`). This works when the
application sees the same host and scheme as the browser.

Behind a reverse proxy that terminates TLS or rewrites `Host`, either configure
the ASGI server to trust the proxy's forwarded headers or list the public
origins:

```python
LiveViewOptions(
    secret=secret,
    allowed_origins=("https://app.example.com", "https://admin.example.com"),
)
```

Origins are normalized to scheme, lowercase host, and explicit port, so
`https://app.example.com` and `https://app.example.com:443` are the same entry.
They may not contain credentials, a path, a query, or a fragment.

## Limits and Close Codes

| Code | Cause |
| --- | --- |
| `1001` | No inbound frame within `idle_timeout_seconds` |
| `1002` | Malformed JSON or an invalid Phoenix Channels message |
| `1003` | Binary frame |
| `1008` | Missing or disallowed `Origin`, or no join before `join_timeout_seconds` |
| `1009` | Inbound frame larger than `max_message_bytes` |
| `1011` | Unexpected exception in a hook, mount, render, or callback |

The Phoenix client sends a heartbeat every 30 seconds, so the default 75-second
idle deadline only closes dead connections. A slow event handler does not use
up the idle deadline, and server pushes do not extend it.

These limits bound abuse per connection. They are not rate limiting; put
connection and request rate limits in the proxy or gateway in front of the
application.

## Delivery Semantics

Each accepted event frame runs its handler at most once. Nothing is retried or
replayed after a disconnect, and a reconnect mounts a fresh page from the
current state of your services. The framework does not make handler side
effects transactional or idempotent:

- keep the source of truth in services and storage, not only in page fields;
- make important actions idempotent or guard them against double submission,
  for example with `phx-disable-with` on submit buttons;
- expect `mount()` to run again at any time.

## Production Checklist

- Serve over TLS so pages and sockets use `https` and `wss`.
- Use a strong secret from configuration, shared by all replicas.
- Configure `allowed_origins` or trusted forwarded headers when a proxy sits in
  front.
- Let the proxy upgrade WebSocket connections on the socket path, with an idle
  timeout longer than the heartbeat interval.
- Authorize in `on_mount` hooks, `mount()`, `handle_params()`, and every
  state-changing `handle_event()`.
- Escape all data: use templates and `attrs()`, never `raw()` or a `str` render
  result for untrusted text. See [Templates and Rendering](templates.md).
- Keep page state that must survive a replica restart in shared storage.

The document loads the client from `client_path` on your own origin and adds no
inline script, so a Content Security Policy with `script-src 'self'` and
`connect-src 'self'` covers the LiveView client itself.

See also the framework-wide [security](../../operations/security.md) and
[deployment](../../operations/deployment.md) guides.
