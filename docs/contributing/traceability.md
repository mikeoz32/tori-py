# Documentation Traceability

Pages anchor complete applications in tested source files under
`examples/tori_py/`. Smaller inline snippets isolate one API rule; package tests
cover their underlying behavior. The D2 pages and their checks are listed below.

| Page | Executable source | Verification |
| --- | --- | --- |
| Home and Why ToriPy | public package facades | `packages/tori-py/tests/test_import_boundaries.py` |
| Installation | package extras and CLI | `packages/tori-py/tests/test_cli.py` |
| First Application | `getting_started/hello_world` | `packages/tori-py/tests/docs/test_getting_started_examples.py` |
| Project Structure | `getting_started/project_structure` | `packages/tori-py/tests/docs/test_getting_started_examples.py` |
| First Controller | `getting_started/hello_world` | `packages/tori-py/tests/docs/test_getting_started_examples.py` |
| First Provider | `getting_started/first_provider` | `packages/tori-py/tests/docs/test_getting_started_examples.py` |
| Configuration | `getting_started/first_settings` | `packages/tori-py/tests/docs/test_getting_started_examples.py` |
| Testing | `getting_started/first_test` | `examples/tori_py/getting_started/first_test/test_example.py` |
| Async factory and ASGI wrapper | `getting_started/async_factory`, `getting_started/asgi_wrapper` | `packages/tori-py/tests/docs/test_getting_started_examples.py` |
| CLI run | `getting_started/cli_run` | `packages/tori-py/tests/test_cli.py` |
| OpenAPI guides | `openapi` | `examples/tori_py/openapi/test_openapi_example.py`, `packages/tori-py-openapi/tests/` |

`packages/tori-py/scripts/verify_docs.py` verifies the required D1/D2 files and
public imports used by Python snippets. `mkdocs build --strict` validates the
site structure, links, and included snippets.

## D0 findings

No public-facade contradiction blocks Getting Started. The only intentional
facade boundary is that `tori_py` does not import optional or driver-specific
APIs. Use `tori_py.http` for framework HTTP contracts, `tori_py.starlette` for the
native transport adapter, and `tori_py.settings`/`tori_py.testing` for their
respective features.
