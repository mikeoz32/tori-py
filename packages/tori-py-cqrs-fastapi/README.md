# tori-py-cqrs-fastapi

`tori-py-cqrs-fastapi` connects `tori-py-cqrs-core` buses to FastAPI
applications through a handler provider that opens a fresh scope for each
dispatch. The CQRS core remains independent of FastAPI and Pydantic.

```bash
uv add tori-py-cqrs-fastapi
```

The package is beta and follows independent Semantic Versioning. See the
[package source](https://github.com/mikeoz32/tori-py/tree/main/packages/tori-py-cqrs-fastapi),
[documentation](https://mikeoz32.github.io/tori-py/), and
[changelog](https://github.com/mikeoz32/tori-py/blob/main/CHANGELOG.md).
