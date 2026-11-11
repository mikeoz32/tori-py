# Build a Live Task Board

This tutorial continues [Part 2: Add CQRS](cqrs-application.md) in the same
`task-api` project and adds an interactive page to it. You will build a task
board at `/board` with [LiveView](../techniques/liveview/index.md): the page is
rendered on the server, creates tasks through the same command bus as the REST
API, validates titles as the user types, and updates every open board when a
task is created anywhere, including through `POST /tasks`.

It branches from Part 2 rather than following Part 4. Parts 3 and 4 distribute
the task service across processes and make reads eventually consistent; this
tutorial keeps one process so the focus stays on LiveView.

The continuity rules are:

- the REST API is unchanged: same routes, payloads, and Problem Details;
- `models.py`, `state.py`, `services.py`, `messages.py`, `observers.py`,
  `handlers.py`, and `http.py` stay exactly as in Part 2;
- the page writes only through `CommandBus` and reads only through `QueryBus`,
  so it follows the same rules as the REST API.

You write no JavaScript. The browser runs the official Phoenix LiveView client
bundled with `tori-py-liveview`.

## What You Will Build

```text
browser tab A ──phx-submit "create"──▶ TaskBoardLive ──CreateTask──▶ CommandBus
                                                                        │
curl POST /tasks ──▶ TaskController ──CreateTask──▶ CommandBus          │
                                                        │               │
                                         TaskCreated ◀──┴───────────────┘
                                              │
                                   AnnounceTaskCreated
                                              │
                                        TaskBoardFeed ── send_info ──▶ every connected board
                                                                          │
                                       handle_info ◀──────────────────────┘
                                              │
                               ListTasks ──▶ stream_insert ──▶ diff to the browser
```

| Feature | LiveView technique |
| --- | --- |
| Initial HTML with the current tasks | Disconnected HTTP mount and render |
| Newest-first task list | A browser-owned stream with a size limit |
| Validation while typing | `phx-change` form events |
| Create a task | `phx-submit` and the command bus |
| Updates from other tabs and the REST API | A CQRS event handler, `send_info()`, and `handle_info()` |
| Live tab title | `title()` |
| Labeled, accessible form and layout | [LiveView UI](../techniques/liveview-ui/index.md) helpers |

## Continue In The Part 2 Project

Open the `task-api` directory you completed in Part 2. Add the two LiveView
distributions from the same checkout:

```text
uv add --editable "../tori-py/packages/tori-py-liveview"
uv add --editable "../tori-py/packages/tori-py-liveview-ui"
```

When this tutorial is complete, the package has this shape:

```text
task-api/
  task_app/
    __init__.py       package marker
    models.py         unchanged
    state.py          unchanged
    services.py       unchanged
    messages.py       unchanged
    observers.py      unchanged
    handlers.py       unchanged
    http.py           unchanged
    feed.py           new
    live.py           new
    app.py            replace
    test_app.py       replace
    browser_e2e.py    new, optional
```

The unchanged files are listed in [Part 2](cqrs-application.md). In particular,
`TaskService.create()` still owns title normalization and validation, and
`CreateTaskHandler` still publishes `TaskCreated` after every successful create.

## Add The Board Feed

A connected board needs to hear about tasks created elsewhere. Create
`task_app/feed.py`:

```python
--8<-- "examples/tori_py/tutorials/live_task_board/task_app/feed.py"
```

`TaskBoardFeed` is a singleton that holds the boards currently connected to
this process. It knows them only through the `BoardSubscriber` protocol, the one
`LiveView` method it needs, so it does not import the page and is easy to test.

`AnnounceTaskCreated` is one more `TaskCreated` handler beside the audit and
metrics observers from Part 2. Like them, it runs asynchronously in its own work
scope after the command returns. It calls `send_info()`, which only queues a
message for each page; the page changes its own state later on its connection
task. This rule matters: a background task must never change page state
directly.

The message carries no task data. It means "the task list changed". Each page
reads the current list itself, which keeps the feed simple and lets a page
recover when a message is dropped.

## Add The Board Page

Create `task_app/live.py`:

```python
--8<-- "examples/tori_py/tutorials/live_task_board/task_app/live.py"
```

### Route and Dependencies

`@live_view("/board")` declares the route. The module registers the page as a
request-scoped provider, so its constructor receives the global `CommandBus` and
`QueryBus` from Part 2 and the `TaskBoardFeed` singleton. The page derives from
`UiLiveView`, which links the LiveView UI stylesheet in the document.

### Mount

`mount()` runs twice for every visit: once for the plain HTTP response
(`connected=False`) and once more when the browser's WebSocket joins
(`connected=True`). Each run uses a new page instance.

Both runs reset the `tasks` stream and insert the current tasks, so the first
HTTP response already shows the list, and a reconnect rebuilds it from the
repository. Only the connected page subscribes to the feed; the HTTP page is
discarded right after rendering.

### Streams

The task list is a [stream](../techniques/liveview/streams.md). The page sends
insert operations and the browser keeps the list items, so the page never holds
all tasks in memory. `at=0` puts each new task at the top, and `limit=50` keeps
the 50 newest items in the browser.

Every inserted item has one root element whose `id` equals the item ID,
`task-<id>`, and the container is rendered with `phx-update="stream"`. The empty
state is a separate element before the container, because the browser preserves
whatever is inside a stream container.

`_show_new_tasks()` inserts only tasks with an ID greater than the last one the
page showed. That makes it safe to call at any time and for any reason: after a
create in this tab, after a wake-up from the feed, or after several wake-ups
were merged or dropped.

### Events

The form helpers render `<form phx-change="validate" phx-submit="create">` with
an input named `task[title]`, so both events receive
`{"task": {"title": "..."}}`.

- `validate` runs on every change. It checks the title rule early and shows the
  error under the field.
- `create` sends the `CreateTask` command. The command is the authority: if
  `TaskService` rejects the title, the page catches `TaskTitleInvalid` and shows
  the same message. On success it clears the draft and shows the new task
  immediately.

The page goes through the command bus instead of calling `TaskService`
directly. Only `CreateTaskHandler` publishes `TaskCreated`, so a direct service
call would create the task without waking the other boards.

Any other event raises `UnknownEventError`. The browser can send arbitrary
events and values, so the `match` statement accepts only the shapes the page
expects.

### Server Updates

`handle_info()` receives the feed's `tasks_changed` message and calls
`_show_new_tasks()`. The diff it produces reaches the browser like the diff of
a browser event. Any other message falls back to the base class, which raises
`UnknownInfoError`.

`disconnect()` runs once when a connected page ends: the tab closes, the user
navigates away, the connection drops, or a callback fails. Unsubscribing there
keeps the feed from holding dead pages.

### Rendering

`render()` builds the page from LiveView UI helpers: `input()` renders a labeled
control whose error text is linked through `aria-describedby`, `form()` binds
the events, and `card()`, `stack()`, `alert()`, and `badge()` provide layout.
Task titles are interpolated into templates, so `<b>` in a title is shown as
text, not markup.

`title()` returns the browser tab title. It is part of every render, so the tab
shows the live task count.

## Replace The Composition Root

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/live_task_board/task_app/app.py"
```

The changes from Part 2 are:

- `TasksModule` provides and exports `TaskBoardFeed` and registers
  `AnnounceTaskCreated` with the other handlers;
- `LiveViewModule.for_root()` registers the board page, the Phoenix client
  script, and the WebSocket endpoint, and imports `TasksModule` so the page can
  receive the feed;
- `LiveViewUiModule.for_root()` serves the UI stylesheet;
- the token secret comes from `TASK_BOARD_SECRET`.

The secret signs the token that ties the WebSocket join to the page the server
rendered. The development fallback exists only so the tutorial runs without
setup. Every deployment must set `TASK_BOARD_SECRET` to a strong value of at
least 32 bytes, shared by all processes that serve the board.

The global validation pipe and error filter from Part 2 still apply to the REST
routes. They also run for the board's HTTP request and WebSocket handshake but
have nothing to do there.

## Replace The Tests

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/live_task_board/task_app/test_app.py"
```

Run it from the project root:

```text
uv run pytest task_app/test_app.py -q
```

The stable result is:

```text
......                                                                   [100%]
6 passed
```

The first three tests are the Part 2 tests and prove that the REST API and the
event fan-out are unchanged. The new tests cover the board:

1. `test_board_renders_existing_tasks_over_http` requests `/board` like a
   browser's first load and checks the escaped, newest-first list, the tab
   title, and the stylesheet link.
2. `test_board_validates_creates_and_catches_up` calls the page's callbacks
   directly with the real buses: early validation, the command's rejection, a
   successful create, and catching up after a task created elsewhere.
3. `test_task_created_wakes_subscribed_boards` proves that `TaskCreated` reaches
   subscribed boards and that unsubscribing stops it, using a small fake board.

These tests do not open a WebSocket. The browser test below covers the real
client.

## Run The Application

Start the application:

```text
uv run tori-py run task_app.app:create_application
```

Open `http://127.0.0.1:8000/board` in two browser tabs.

1. Type spaces into the title field. The error appears under the field while
   you type.
2. Type a real title and press Enter. The task appears at the top of both tabs,
   the field clears, and both tab titles show the new count.
3. Create a task through the unchanged REST API from another PowerShell
   session:

```powershell
'{"title":"Created over REST"}' | curl.exe --silent --request POST "http://127.0.0.1:8000/tasks" --header "content-type: application/json" --data-binary '@-' --write-out "`nHTTP %{http_code}`n"
```

The response is the same as in Part 2, and the task appears on both boards
without a reload.

Stop the server and start it again: open boards reconnect on their own and
mount fresh pages. Because the repository is in memory, the restarted process
has no tasks.

## Add A Browser Test

The unit and HTTP tests stop at the server. A browser test runs the official
Phoenix client against a real server. Add the Playwright pytest plugin and
install Chromium once:

```text
uv add --dev pytest-playwright
uv run playwright install chromium
```

Create `task_app/browser_e2e.py`:

```python
--8<-- "examples/tori_py/tutorials/live_task_board/task_app/browser_e2e.py"
```

The fixture starts Uvicorn on a free port in a background thread. The test
opens two tabs, waits for each live root to report `phx-connected`, then checks
live validation, creating a task, the cleared field, a REST-created task
reaching both tabs, the newest-first order, the tab titles, and the absence of
browser errors.

Run it explicitly:

```text
uv run pytest task_app/browser_e2e.py
```

The file name does not start with `test_`, so `pytest` does not collect it by
default and the fast suite keeps working without a browser.

## Guarantees And Limits

- **One process.** `TaskBoardFeed` and the repository live in one process. With
  several workers or replicas, a board is woken only by tasks created in its own
  process, and each process has its own tasks. A multi-process board needs
  shared storage and a shared notification channel; Parts 3 and 4 show the
  distribution building blocks.
- **Wake-ups can be dropped.** Each page queues at most 32 messages. A dropped
  wake-up is repaired by the next one, because the page always catches up from
  its last ID. If no further change happens, that board stays behind until the
  next change or a reload.
- **Reconnects rebuild.** A reconnect or server restart mounts a fresh page from
  the repository. The server keeps no page state after a disconnect.
- **No authentication.** Like the REST API in these tutorials, anyone who can
  open `/board` can create tasks. Add authorization in
  [mount hooks](../techniques/liveview/navigation.md#authorization) and in the
  `create` handler before exposing the board.
- **Events run at most once.** A create that fails is not retried. Double
  submission is possible; make important commands idempotent.
- **Deployment.** Serve the board over TLS, set `TASK_BOARD_SECRET`, and make
  sure the proxy upgrades WebSockets. See
  [LiveView configuration and security](../techniques/liveview/configuration-and-security.md).

## Next Steps

- [Pages and Lifecycle](../techniques/liveview/pages.md): the complete callback
  and event-value reference.
- [Stateful Components](../techniques/liveview/components.md): give each task
  its own inline editor.
- [JS Commands](../techniques/liveview/js-commands.md): add client-side
  transitions without JavaScript files.
- [Routing and Navigation](../techniques/liveview/navigation.md): add
  `/board/{task_id}` with `handle_params` and live patches.
- [Testing LiveView](../techniques/liveview/testing.md): testing strategies for
  larger pages.
