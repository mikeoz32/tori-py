# Routing and Navigation

LiveView routes are ordinary `GET` routes compiled with the same Starlette path
patterns as controllers. A page can serve several routes, update its URL without
remounting, move to another page over the open socket, or force a full page
load.

## Several Routes per Page

Stack `@live_view` declarations. `action` names each route and is exposed as
`live_action`:

```python
from string.templatelib import Template

from tori_py_liveview import LiveView, UnknownEventError, live_view


@live_view("/articles/{slug}", action="show")
@live_view("/articles/new", action="new")
@live_view("/articles", action="index")
class ArticlesLive(LiveView):
    def __init__(self) -> None:
        self.page = 1
        self.slug: str | None = None

    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        self.page = int(params.get("page", "1"))
        self.slug = params.get("slug")

    async def handle_event(self, event: str, value: object) -> None:
        if event == "next":
            self.push_patch(f"/articles?page={self.page + 1}")
        elif event == "compose":
            self.push_patch("/articles/new")
        else:
            raise UnknownEventError(event)

    def render(self) -> Template:
        match self.live_action:
            case "new":
                return t"<h1>New article</h1>"
            case "show":
                return t"<h1>{self.slug}</h1>"
            case _:
                return (
                    t"<h1>Articles, page {self.page}</h1>"
                    t'<button phx-click="next">Next</button>'
                )
```

Paths must be absolute, unique within the module, and free of query strings.
Path parameters use Starlette syntax, including converters such as
`{article_id:int}`, but always reach the page as strings.

Routes match in registration order, and decorators apply from the bottom up:
the declaration closest to the class is registered first. Keep a parameterized
route such as `/articles/{slug}` above the static routes it would otherwise
shadow, as in the example, or `/articles/new` would render as an article named
`new`. Across pages, routes follow the order of `pages=`.

## `handle_params`

`handle_params(params, uri)` runs after every `mount()` and after every patch.
`params` merges the query string with the path parameters, and path parameters
win on a name clash. All values are strings. `uri` is the full URL. Parse
parameters here rather than in `mount()` so that patches and first loads share
one code path.

## Three Ways to Move

| Server call | Client equivalent | What happens |
| --- | --- | --- |
| `push_patch(to, kind="push")` | `data-phx-link="patch"` link or `JS().patch(to)` | Same page instance: URL changes, `handle_params` runs, page renders |
| `push_navigate(to, kind="push")` | `data-phx-link="redirect"` link or `JS().navigate(to)` | Current page disconnects; a new page mounts over the same socket |
| `redirect(to)` | A normal link | Full browser page load |

`kind="replace"` replaces the browser history entry instead of adding one.
Client links use the official Phoenix attributes:

```html
<a href="/articles?page=2" data-phx-link="patch" data-phx-link-state="push">Next</a>
<a href="/settings" data-phx-link="redirect" data-phx-link-state="push">Settings</a>
```

The `href` keeps the links working without JavaScript.

### Rules

- Navigation requested in a callback applies after that callback returns. Only
  the last call in one callback counts.
- `push_patch()` must resolve to a route of the current page class in the same
  session. Use `push_navigate()` to reach another page.
- `push_navigate()` works between pages of the same live session. A target in a
  different session falls back to a full page load.
- Patch and navigate targets must be same-origin paths or URLs.
- `handle_params` may patch again; a chain longer than 20 patches fails.
- Calling `redirect()` or `push_navigate()` from `mount()` or `handle_params()`
  during the HTTP render returns `302 Found` to the target instead of a page.

A navigation rule violation raises `LiveViewError`. In a connected page, that
closes the socket with `1011` like any other callback failure.

### Safe Redirects

`redirect(to)` accepts a root-relative path or an `http`/`https` URL. It cleans
the target the way browsers read it, so values such as `/\evil.example` cannot
escape to another host. The host must be the request host or one of
`LiveViewOptions.redirect_hosts`:

<!-- docs-test: skip -->

```python
from tori_py_liveview import LiveViewOptions

options = LiveViewOptions(
    secret=secret,
    redirect_hosts=("login.example.com",),
)
```

That makes `redirect(context.query_params["next"])` safe for a `?next=`
parameter. A target with another scheme raises `LiveViewError` from
`redirect()`, and a target on an unlisted host fails with `LiveViewError` when
the navigation is applied. Either way the visitor is not sent to the other site.
Check the value yourself first if you prefer a friendly fallback to an error.

## Live Sessions and Mount Hooks

A `LiveSession` groups pages that can navigate to each other over one socket and
share mount hooks. Pages without `session=` belong to the unnamed default
session.

<!-- docs-test: skip -->

```python
from tori_py_liveview import LiveSession, LiveViewModule

liveview_module = LiveViewModule.for_root(
    options,
    pages=[ArticlesLive, SettingsLive, AdminLive],
    sessions=[
        LiveSession("members", on_mount=(require_member,)),
        LiveSession("admin", on_mount=(require_member, require_admin)),
    ],
)
```

Assign a page with `@live_view(path, session="members")`. Every page using a
session name must list that session in `for_root()`, and session names are
unique.

`on_mount` hooks are called as `hook(page, context)` in order, before
`mount()`, on the HTTP render and on every connected join: first connect,
reconnect, and live navigation. A hook may be a plain function or return an
awaitable.

## Authorization

Global pipeline guards run for the HTTP page request and for the WebSocket
handshake. They do not run again for a live navigation, which joins a new page
over the open socket, and they never run for individual events. Put access checks
where every mount passes through them:

```python
from starlette.requests import HTTPConnection

from tori_py_liveview import LiveView, MountContext


class Accounts:
    async def member_for(self, session_cookie: str | None) -> str | None: ...


class MemberPage(LiveView):
    def __init__(self, accounts: Accounts) -> None:
        self.accounts = accounts
        self.member: str | None = None


async def require_member(page: LiveView, context: MountContext) -> None:
    if not isinstance(page, MemberPage):
        raise TypeError("require_member needs a MemberPage")
    if not isinstance(context.request, HTTPConnection):
        raise TypeError("unexpected mount request")
    cookie = context.request.cookies.get("session")
    page.member = await page.accounts.member_for(cookie)
    if page.member is None:
        page.redirect("/login")
```

A redirect requested by a hook takes effect after `mount()` and
`handle_params()` and before the first render, so those callbacks still run.
Skip data loading and side effects when the hook rejected the visitor:

```python
async def mount(self, context: MountContext) -> None:
    if self.member is None:
        return
    self.articles = await self.store.for_member(self.member)
```

Raising from a hook also stops the mount: the HTTP render then fails through the
normal exception filters, and a connected join closes with `1011`, after which
the client keeps reconnecting. A redirect gives the visitor a clearer result.

Authorize state-changing actions again in `handle_event()`. A mounted page
proves who connected, not that every event value is allowed.
