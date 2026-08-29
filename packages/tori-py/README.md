# tori-py-framework

`tori-py-framework` is the core Tori Py application framework. It provides explicit
modules, dependency injection, lifecycle management, configuration, testing
utilities, and a Starlette ASGI driver for Python 3.14 applications.

```bash
uv add tori-py-framework
```

Optional extras provide CLI and testing dependencies:

```bash
uv add "tori-py-framework[cli,testing]"
```

The package is beta and follows independent Semantic Versioning. See the
[Tori Py documentation](https://github.com/mikeoz32/tori-py/tree/main/docs),
[repository](https://github.com/mikeoz32/tori-py), and
[changelog](https://github.com/mikeoz32/tori-py/blob/main/CHANGELOG.md).

Routes that require an empty request stream can opt in with `@no_body`. Tori Py
checks the actual stream after guards and rejects content before pipes,
interceptors, or the handler. Cumulative content at or below the configured
limit returns 400; content above it returns 413 regardless of stream chunking.
