# Documentation Traceability

Pages use tested source files under `examples/nestpy/` rather than copied
snippets. The D2 pages and their checks are listed below.

| Page | Executable source | Verification |
| --- | --- | --- |
| Home and Why Nestpy | public package facades | `packages/nestpy/tests/test_import_boundaries.py` |
| Installation | package extras and CLI | `packages/nestpy/tests/test_cli.py` |
| First Application | `getting_started/hello_world` | `packages/nestpy/tests/docs/test_getting_started_examples.py` |
| Project Structure | `getting_started/project_structure` | `packages/nestpy/tests/docs/test_getting_started_examples.py` |
| First Controller | `getting_started/hello_world` | `packages/nestpy/tests/docs/test_getting_started_examples.py` |
| First Provider | `getting_started/first_provider` | `packages/nestpy/tests/docs/test_getting_started_examples.py` |
| Configuration | `getting_started/first_settings` | `packages/nestpy/tests/docs/test_getting_started_examples.py` |
| Testing | `getting_started/first_test` | `examples/nestpy/getting_started/first_test/test_example.py` |
| Async factory and ASGI wrapper | `getting_started/async_factory`, `getting_started/asgi_wrapper` | `packages/nestpy/tests/docs/test_getting_started_examples.py` |
| CLI run | `getting_started/cli_run` | `packages/nestpy/tests/test_cli.py` |

`packages/nestpy/scripts/verify_docs.py` verifies the required D1/D2 files and
public imports used by Python snippets. `mkdocs build --strict` validates the
site structure, links, and included snippets.

## D0 findings

No public-facade contradiction blocks Getting Started. The only intentional
facade boundary is that `nestpy` does not import optional or driver-specific
APIs. Use `nestpy.settings`, `nestpy.starlette`, and `nestpy.testing` directly
for those features.
