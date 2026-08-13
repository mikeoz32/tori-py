# Installation

ToriPy requires Python 3.14 and uses [uv](https://docs.astral.sh/uv/) for
environments and commands.

Create a project and install the base framework:

```text
uv init my-tori_py-app
cd my-tori_py-app
uv add tori_py
```

Install an optional extra only when the application needs it:

```text
uv add 'tori_py[settings-yaml]'
uv add 'tori_py[cli]'
uv add --dev 'tori_py[testing]'
```

`settings-yaml` enables YAML settings files. `cli` installs Uvicorn for the
`tori-py run` command. `testing` installs HTTPX for the standard async HTTP test
client. The base package does not eagerly import these optional dependencies.

The examples in this repository run from its root after:

```text
uv sync --all-packages --all-groups --extra cli
```
