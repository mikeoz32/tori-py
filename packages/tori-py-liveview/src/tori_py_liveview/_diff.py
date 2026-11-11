"""Encode renders as Phoenix render trees that carry only what the client lacks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from tori_py_liveview.rendering import (
    Rendered,
    _ChildRendered,
    _ComponentRendered,
    _RenderedDynamic,
    _StreamRendered,
)


class _Unchanged:
    __slots__ = ()


# Marks a dynamic the client already holds, so its key stays out of the diff.
_UNCHANGED: Final = _Unchanged()


def _stream_tree(rendered: _StreamRendered) -> dict[str, object]:
    keyed: dict[str, object] = {"kc": len(rendered.inserts)}
    insert_metadata: list[list[object]] = []
    for index, insert in enumerate(rendered.inserts):
        keyed[str(index)] = {"0": insert.html}
        insert_metadata.append([insert.item_id, insert.at, insert.limit, None])
    stream: list[object] = [
        rendered.ref,
        insert_metadata,
        list(rendered.delete_ids),
    ]
    if rendered.reset:
        stream.append(True)
    return {"s": ["", ""], "k": keyed, "stream": stream}


def _stream_operations(rendered: _StreamRendered) -> bool:
    return bool(rendered.inserts or rendered.delete_ids or rendered.reset)


class _RenderState:
    """The render tree one joined client holds, so later renders send changes.

    The official client caches the page tree and each component tree by CID.
    A node without statics merges into the cached node at its position, and a
    node with statics replaces it. New page statics replace the whole page tree
    and drop every cached component. Component trees otherwise stay cached
    until the client prunes them after the server confirms `cids_destroyed`.
    """

    __slots__ = ("_components", "_main", "_root", "_title")

    def __init__(self, *, main: bool = True) -> None:
        # Only the main view owns the document title.
        self._main = main
        self._root: Rendered | None = None
        self._components: dict[int, Rendered] = {}
        self._title: str | None = None

    def encode(self, rendered: Rendered, title: str | None) -> dict[str, object]:
        """Encode a render against the client's tree and record what it now holds."""
        if isinstance(rendered, _ComponentRendered):
            rendered = Rendered(("", ""), (rendered,))
        previous = self._root
        if previous is not None and previous.statics == rendered.statics:
            encoder = _Encoder(self._components)
            payload = encoder.changed(rendered, previous)
        else:
            encoder = _Encoder({})
            payload = encoder.full(rendered)
        encoder.share_statics()
        if encoder.trees:
            payload["c"] = encoder.trees
        if self._main and (previous is None or title != self._title):
            payload["t"] = "" if title is None else title
        elif not self._main and title is not None and title != self._title:
            # The client writes any string title, and an empty one clears the
            # page's, so a child sends only a title it sets.
            payload["t"] = title
        self._root = rendered
        self._components = encoder.components
        self._title = title
        return payload

    def forget(self, cids: Iterable[int]) -> None:
        """Drop component trees the client prunes after `cids_destroyed`."""
        for cid in cids:
            self._components.pop(cid, None)


class _Encoder:
    """Encode one render, collecting its component trees under `c`."""

    __slots__ = ("_cached", "_fresh", "_kept", "components", "trees")

    def __init__(self, cached: dict[int, Rendered]) -> None:
        # Component trees the client holds before and after this render.
        self._cached = cached
        self.components = dict(cached)
        self.trees: dict[str, object] = {}
        # Components sent with statics, and cached statics of kept components.
        self._fresh: list[tuple[int, tuple[str, ...], dict[str, object]]] = []
        self._kept: dict[tuple[str, ...], int] = {}

    def full(self, rendered: Rendered, *, root: bool = False) -> dict[str, object]:
        tree: dict[str, object] = {"s": list(rendered.statics)}
        if root:
            tree["r"] = 1
        for index, value in enumerate(rendered.dynamics):
            tree[str(index)] = self._full_value(value)
        return tree

    def changed(self, rendered: Rendered, previous: Rendered) -> dict[str, object]:
        tree: dict[str, object] = {}
        for index, (value, before) in enumerate(
            zip(rendered.dynamics, previous.dynamics, strict=True)
        ):
            encoded = self._changed_value(value, before)
            if encoded is not _UNCHANGED:
                tree[str(index)] = encoded
        return tree

    def share_statics(self) -> None:
        """Send each component template's statics once, as the client allows.

        A positive CID copies statics from a component in this diff and a
        negative one from a cached component. Only components this render keeps
        lend cached statics: the client may prune any other one before it
        applies a deferred diff. The dynamics each tree sends in full replace
        the ones the client copies with the statics.
        """
        sent: dict[tuple[str, ...], int] = {}
        for cid, statics, tree in self._fresh:
            cached = self._kept.get(statics)
            if cached is not None:
                tree["s"] = -cached
            elif statics in sent:
                tree["s"] = sent[statics]
            else:
                sent[statics] = cid

    def _full_value(self, value: _RenderedDynamic) -> object:
        if isinstance(value, _ComponentRendered):
            return self._component(value)
        if isinstance(value, _StreamRendered):
            return _stream_tree(value)
        if isinstance(value, _ChildRendered):
            return value.value
        if isinstance(value, Rendered):
            return self.full(value)
        return value

    def _changed_value(
        self,
        value: _RenderedDynamic,
        before: _RenderedDynamic,
    ) -> object:
        if isinstance(value, _ComponentRendered):
            cid = self._component(value)
            moved = not isinstance(before, _ComponentRendered) or before.cid != cid
            return cid if moved else _UNCHANGED
        if isinstance(value, _StreamRendered):
            # Each render consumes its operations and the client prunes stream
            # entries once it applies them, so the same stream without
            # operations has nothing to send.
            if (
                isinstance(before, _StreamRendered)
                and before.ref == value.ref
                and not _stream_operations(value)
            ):
                return _UNCHANGED
            return _stream_tree(value)
        if isinstance(value, _ChildRendered):
            # The client keeps a joined child's container and contents.
            if isinstance(before, _ChildRendered) and before.value == value.value:
                return _UNCHANGED
            return value.value
        if isinstance(value, Rendered):
            if type(before) is Rendered and before.statics == value.statics:
                return self.changed(value, before) or _UNCHANGED
            return self.full(value)
        if isinstance(before, str) and before == value:
            return _UNCHANGED
        return value

    def _component(self, rendered: _ComponentRendered) -> int:
        cid = rendered.cid
        body = Rendered(rendered.statics, rendered.dynamics)
        before = self._cached.get(cid)
        self.components[cid] = body
        if before is not None:
            self._kept.setdefault(before.statics, cid)
            if before.statics == body.statics:
                tree = self.changed(body, before)
                if tree:
                    self.trees[str(cid)] = tree
                return cid
        tree = self.full(body, root=True)
        self.trees[str(cid)] = tree
        self._fresh.append((cid, body.statics, tree))
        return cid
