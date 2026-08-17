# Task API Reference Application

This is a composed ToriPy v1 example, not a production task service. It shows:

- static modules and a global dynamic settings module;
- class, value, and request-scoped factory providers;
- singleton repository lifecycle cleanup;
- controller bindings and `MsgspecValidationPipe`;
- a guard for writes;
- a domain filter for task errors;
- ASGI factory and CLI usage.

Run it with the optional CLI extra:

```text
uv add 'tori-py-framework[cli]'
tori-py run examples.tori_py.reference_apps.task_api.app:create_application
```

For direct ASGI hosting, use the exported wrapper:

```text
uvicorn examples.tori_py.reference_apps.task_api.app:application
```

Create a task:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" -H "x-task-write: allow" -d "{\"title\":\"Read ToriPy guides\"}"
```

List tasks:

```powershell
curl.exe "http://127.0.0.1:8000/tasks"
```

The repository is intentionally in-memory. Persistence, authentication, and
authorization policy are application concerns outside ToriPy v1.
