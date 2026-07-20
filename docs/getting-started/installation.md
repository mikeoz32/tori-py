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
```

`settings-yaml` enables YAML settings files. `cli` installs Uvicorn for the
`nestpy run` command. The core package does not import either optional feature.

The examples in this repository run from its root after:

```text
uv sync --all-packages --all-groups --extra cli
```
