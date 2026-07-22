# Installation

Nestpy requires Python 3.14 and uses [uv](https://docs.astral.sh/uv/) for
environments and commands.

Create a project and install the base framework:

```text
uv init my-nestpy-app
cd my-nestpy-app
uv add nestpy
```

Install an optional extra only when the application needs it:

```text
uv add 'nestpy[settings-yaml]'
uv add 'nestpy[cli]'
uv add --dev 'nestpy[testing]'
```

`settings-yaml` enables YAML settings files. `cli` installs Uvicorn for the
`nestpy run` command. `testing` installs HTTPX for the standard async HTTP test
client. The base package does not eagerly import these optional dependencies.

The examples in this repository run from its root after:

```text
uv sync --all-packages --all-groups --extra cli
```
