# Add a Live Task Feed with WebSockets

This tutorial continues [Part 1: Build a Task API](task-api.md) in the same
`task-api` project. It adds a [WebSocket gateway](../websockets.md) at
`/tasks/live`: a connected client receives the current tasks and then every
task created afterwards, whether the task came from the REST API or anywhere
else in the process.

It branches from Part 1 rather than following Part 2, so the feed sits next to
the plain service. For a server-rendered page that updates itself, see the
[Live Task Board](live-task-board.md), which uses LiveView instead of a raw
WebSocket protocol.

The continuity rules are:

- the REST API is unchanged: same routes, payloads, and Problem Details;
- `models.py`, `state.py`, and `http.py` stay exactly as in Part 1;
- the service notifies the feed after each create, and nothing else changes in
  how a task is created.

## What You Will Build

```text
client ── WS /tasks/live ──▶ BrowserOriginGuard ──▶ TaskFeedGateway.handle
                                                         │
          ◀── {"type":"snapshot","tasks":[...]} ─────────┤
                                                         │ waits on its wake-up
POST /tasks ─▶ TaskService.create ─▶ TaskFeed.notify ────┤
                                                         │ reads tasks after last ID
          ◀── {"type":"created","task":{...}} ───────────┘
```

| Feature | Technique |
| --- | --- |
| A WebSocket endpoint | `@websocket_gateway` registered as a provider |
| Per-connection state that cleans itself up | A request-scoped `FactoryProvider` around an async context manager |
| Rejecting other websites | A guard that checks `Origin` before the handshake is accepted |
| Noticing a closed connection while idle | A receive loop next to the sender in `asyncio.TaskGroup` |
| No lost or duplicate messages | Catch-up by last sent ID instead of a message queue |
| Typed JSON messages | Tagged `msgspec` structs |
| Tests | Starlette's `TestClient` |

## Continue In The Part 1 Project

Open the `task-api` directory you completed in Part 1. There is nothing to
install: WebSocket gateways are part of `tori-py-framework`, and the `testing`
extra already provides the HTTP client that Starlette's `TestClient` uses.

When this tutorial is complete, the package has this shape:

```text
task-api/
  task_app/
    __init__.py       package marker
    models.py         unchanged
    state.py          unchanged
    http.py           unchanged
    feed.py           new
    services.py       replace
    live.py           new
    app.py            replace
    test_app.py       replace
```

## Step 1: Wake Connections When Tasks Change

Create `task_app/feed.py`:

```python
--8<-- "examples/tori_py/tutorials/websocket_task_feed/task_app/feed.py"
```

`TaskFeed` holds one `asyncio.Event` per subscribed connection. `notify()` sets
every event; it does not carry the task itself. Each connection reads the new
tasks from the service when it wakes. Several creates in a row therefore cost
one wake-up, and a slow client cannot make the feed hold an unbounded backlog.

`subscribe()` is an async context manager: the event exists only while the
`async with` block is open, and leaving the block removes it whatever the
reason.

## Step 2: Notify From The Service

Replace `task_app/services.py`:

```python
--8<-- "examples/tori_py/tutorials/websocket_task_feed/task_app/services.py"
```

`create()` notifies the feed after the repository stores the task, so a woken
connection always finds it. `created_after()` returns the tasks a connection has
not sent yet.

## Step 3: Write The Gateway

Create `task_app/live.py`:

```python
--8<-- "examples/tori_py/tutorials/websocket_task_feed/task_app/live.py"
```

### Messages

`Snapshot` and `Created` are tagged structs: encoding one adds a `type` field
with the tag, so clients can switch on `type`. The gateway writes them as text
frames, because JSON is text.

### Per-connection subscription

`subscribe(feed)` returns the feed's context manager. Step 4 registers it as a
request-scoped `FactoryProvider`. ToriPy opens one request scope per WebSocket
connection and enters managed provider results, so each connection gets its own
`asyncio.Event`, and the subscription ends when the connection's scope closes:
after a normal return, a disconnect, an error, or cancellation. The gateway
never has to unsubscribe.

### Origin check

A browser sends an `Origin` header with every WebSocket handshake, and unlike
`fetch()`, a WebSocket handshake is not limited by the same-origin policy. Without
a check, any website a user visits could open `/tasks/live` from the user's
browser. `BrowserOriginGuard` accepts only the origins that serve this
application. Clients that are not browsers usually send no `Origin`; the guard
lets them through, because the check protects browsers, not the endpoint.

Guards run before the handshake is accepted. A denied connection never reaches
`handle()`.

### Connection lifetime

ToriPy never accepts a WebSocket for you, so `handle()` starts with
`socket.accept()`.

The gateway then needs to do two things at once: send tasks when the feed wakes
it, and notice when the client goes away. A sender that waits on the event alone
would not see a closed connection until the next task arrives. `handle()`
therefore runs the sender as a task in an `asyncio.TaskGroup` and reads incoming
frames until the disconnect message arrives. Clients are not expected to send
anything, so other frames are ignored. When the client disconnects, `handle()`
cancels the sender and returns.

If the sender fails, the task group cancels the receive loop and raises the
error, and ToriPy closes the connection with code `1011`.

### Catch-up by ID

`_send_tasks()` sends the snapshot and remembers the last ID it sent. After every
wake-up it sends the tasks created after that ID. The connection subscribes
before `handle()` runs, so a task created between the subscription and the
snapshot is either in the snapshot or produces a wake-up, and the ID comparison
sends it exactly once.

## Step 4: Compose The Application

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/websocket_task_feed/task_app/app.py"
```

- `TaskFeed` is a singleton exported next to `TaskRepository`, so the service and
  the subscription share one feed.
- `FactoryProvider(TASK_WAKEUP, subscribe, scope=Scope.REQUEST)` creates the
  per-connection subscription. `ClassProvider` and `FactoryProvider` manage
  their results by default, which is what enters and exits the context manager.
- `TaskFeedGateway` is listed in `providers`. A gateway is an ordinary singleton
  provider; the decorator registers nothing globally.

## Step 5: Run The Application

Start the server from the `task-api` root:

```text
uv run tori-py run task_app.app:create_application
```

Open `http://127.0.0.1:8000/tasks` in a browser, then run this in the developer
console. The page's origin, `http://127.0.0.1:8000`, is allowed:

```javascript
const feed = new WebSocket("ws://127.0.0.1:8000/tasks/live");
feed.onmessage = (event) => console.log(JSON.parse(event.data));
```

The console prints the snapshot. Create a task from a terminal:

=== "PowerShell"

    ```powershell
    '{"title":"Watch me arrive"}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    ```

=== "Bash"

    ```bash
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" \
      --data '{"title":"Watch me arrive"}'
    ```

The console prints `{type: "created", task: {...}}` for the new task.

Stop the server with `Ctrl+C`. Uvicorn closes open WebSocket connections with
code `1012`, the gateway sees a disconnect, and the subscription ends like any
other.

## Step 6: Test The Feed

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/websocket_task_feed/task_app/test_app.py"
```

The two Part 1 tests are unchanged, except that the service test passes a
`TaskFeed`. The new tests check that:

1. a client receives the snapshot, then one `created` message for each task
   created through `POST /tasks` while it is connected, and that a client from
   an allowed origin can connect;
2. a handshake from another origin is denied;
3. a subscription is removed when its context ends.

`TestClient` runs the application's lifespan and opens real WebSocket sessions
in-process. It is synchronous, so the WebSocket tests are plain functions, and
the same client can send HTTP requests while a WebSocket session is open.

A denied handshake appears differently to different clients. `TestClient`
raises `WebSocketDisconnect` with code `1008`. A real server such as Uvicorn
answers the handshake with HTTP `403`, and a browser reports a failed
connection.

Run the tests:

```text
uv run pytest task_app/test_app.py -q
```

Expected result: `5 passed`.

## What Happens When

| Event | Result |
| --- | --- |
| The client disconnects | The receive loop returns, the sender is cancelled, `handle()` returns, and the connection's scope closes and unsubscribes |
| Another website opens the feed | The guard denies the handshake; `handle()` never runs |
| The server stops | Uvicorn closes the connection with `1012`, which the gateway handles as a disconnect |
| A handler does not finish during shutdown | ToriPy drains active connections with the same bounded policy as HTTP requests, then cancels them |
| Sending fails | The task group cancels the receive loop, and ToriPy closes the connection with `1011` |

## Guarantees And Limits

- **One process.** `TaskFeed` wakes connections in its own process only. With
  several workers or replicas, a client hears about tasks created in its
  process. A shared notification channel is needed across processes.
- **Origin is not authentication.** The guard stops other websites from using a
  visitor's browser. It does not identify users; anyone who can reach the server
  from a non-browser client can read the feed.
- **Reconnects start over.** The server keeps nothing after a disconnect. A
  client that reconnects receives a new snapshot, which also repairs anything it
  missed while disconnected.
- **The snapshot is the whole list.** It grows with the number of tasks. Send a
  page or a recent window in a larger application.
- **Clients only listen.** Incoming frames are ignored. A protocol that accepts
  commands needs validation and limits for every message.

## Next Steps

- [WebSockets](../websockets.md): bindings, the pipeline order, close codes, and
  shutdown.
- [Scopes and Resources](../fundamentals/scopes-and-resources.md): request
  scopes and managed provider resources.
- [Build a Live Task Board](live-task-board.md): a server-rendered page with
  the same kind of live updates, without writing a protocol.
