"""Driver-neutral pipeline declarations and provider fallback discovery."""

from dataclasses import dataclass

from tori_py.core.compiler import CompiledGraph
from tori_py.core.errors import BootstrapError
from tori_py.core.metadata import get_pipeline_metadata, get_route_metadata
from tori_py.core.modules import ModuleSpec
from tori_py.core.options import PipelineOptions
from tori_py.core.providers import ClassProvider


@dataclass(frozen=True, slots=True)
class PipelineBindings:
    middleware: tuple[object, ...] = ()
    guards: tuple[object, ...] = ()
    pipes: tuple[object, ...] = ()
    interceptors: tuple[object, ...] = ()
    filters: tuple[object, ...] = ()


_ENHANCER_METHODS = {
    "guards": "can_activate",
    "pipes": "transform",
    "interceptors": "intercept",
    "filters": "catch",
}


def pipeline_class_provider_fallbacks(
    spec: ModuleSpec,
    *,
    is_root: bool,
    global_bindings: PipelineOptions,
) -> tuple[ClassProvider, ...]:
    """Return enhancer classes that can back unresolved registrations."""

    bindings: list[tuple[str, object]] = []
    for controller in spec.controllers:
        route_handlers = tuple(
            handler
            for handler in controller.__dict__.values()
            if get_route_metadata(handler) is not None
        )
        if not route_handlers:
            continue
        for kind in _ENHANCER_METHODS:
            bindings.extend(
                (kind, binding) for binding in get_pipeline_metadata(controller, kind)
            )
        for handler in route_handlers:
            for kind in _ENHANCER_METHODS:
                bindings.extend(
                    (kind, binding) for binding in get_pipeline_metadata(handler, kind)
                )
    if is_root:
        for kind in _ENHANCER_METHODS:
            bindings.extend(
                (kind, binding) for binding in getattr(global_bindings, kind)
            )

    providers: list[ClassProvider] = []
    collected: set[type[object]] = set()
    for kind, binding in bindings:
        if (
            isinstance(binding, type)
            and callable(getattr(binding, _ENHANCER_METHODS[kind], None))
            and binding not in collected
        ):
            providers.append(ClassProvider(binding, binding))
            collected.add(binding)
    return tuple(providers)


def validate_pipeline_options(
    graph: CompiledGraph,
    options: PipelineOptions,
) -> None:
    """Validate application-wide provider registrations against root visibility."""

    for kind in (
        "middleware",
        "guards",
        "pipes",
        "interceptors",
        "filters",
    ):
        for binding in getattr(options, kind):
            if not isinstance(binding, str | type):
                continue
            if (graph.root, binding) not in graph.visibility:
                raise BootstrapError(
                    "pipeline provider is not visible from the root module",
                    code="provider.unresolved",
                    details={"kind": kind, "token": repr(binding)},
                )


__all__ = ["PipelineBindings"]
