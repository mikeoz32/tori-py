# ToriPy LiveView Kit

`tori-py-liveview-kit` is a separately installable package for prototyping AI
applications on `tori-py-liveview` and `tori-py-liveview-ui`. It is the layer
that owns state: a chat page that keeps a conversation, a provider-neutral model
event stream, a streaming runtime that owns the model task, and a launcher with
development defaults.

```bash
uv add tori-py-liveview-kit
```

The optional `highlight` extra colors code blocks in replies:

```bash
uv add "tori-py-liveview-kit[highlight]"
```

The package contains no model client and no provider SDK. The application
supplies the model call, tool execution, persistence, and authentication.
