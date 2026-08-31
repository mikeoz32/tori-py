# Contributing to Tori Py

Tori Py requires Python 3.14 and uses `uv` for environments, dependencies,
commands, tests, and builds.

## Development

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Run the repository's `ty` command from `AGENTS.md` when changing Python code.
Broker integration tests additionally require the documented Docker and
RabbitMQ setup.

Build and verify the documentation with the isolated docs group:

```bash
uv sync --locked --group docs
uv run python packages/tori-py/scripts/verify_docs.py
uv run python packages/tori-py-microservices/scripts/verify_docs.py
uv run --group docs mkdocs build --strict
```

Use `uv run --group docs mkdocs serve` for a local documentation server. Do not
commit the generated `site/` directory.

Keep packages independently installable and preserve framework-neutral package
boundaries. Add or update tests for behavior changes. Update package READMEs and
the root changelog when public APIs, guarantees, or operational constraints
change.

## Changes

Open a focused pull request against the future public repository at
<https://github.com/mikeoz32/tori-py>. Explain the problem, the chosen behavior,
tests run, and compatibility impact. Do not commit generated sites, build
artifacts, credentials, or personal data.

Unless explicitly stated otherwise, intentionally submitted contributions are
licensed under the Apache License 2.0 as described in [LICENSE](LICENSE).
