from __future__ import annotations

import copy
import json
import random
from typing import cast

import pytest
from tori_py_liveview import Rendered
from tori_py_liveview._diff import _RenderState
from tori_py_liveview.rendering import (
    _ComponentRendered,
    _StreamInsert,
    _StreamRendered,
)

type _Tree = dict[str, object]


# A port of the pinned Phoenix LiveView 1.2.11 client's Rendered merge and
# render, enough to check that changed-only diffs rebuild every render.


def _is_object(value: object) -> bool:
    return isinstance(value, dict)


def _client_merge(state: _Tree | None, payload: _Tree) -> _Tree:
    diff = copy.deepcopy(payload)
    for key in ("t", "e", "r"):
        diff.pop(key, None)
    components = cast(dict[str, _Tree] | None, diff.pop("c", None))
    if state is None or "s" in diff:
        rendered = diff
    else:
        _do_mutable_merge(state, diff)
        rendered = state
    cache = cast(dict[str, _Tree], rendered.setdefault("c", {}))
    if components:
        resolved: dict[str, _Tree] = {}
        for cid in list(components):
            components[cid] = _find_component(
                cid, components[cid], cache, components, resolved
            )
        cache.update(components)
    return rendered


def _find_component(
    cid: str,
    tree: _Tree,
    cache: dict[str, _Tree],
    components: dict[str, _Tree],
    resolved: dict[str, _Tree],
) -> _Tree:
    if cid in resolved:
        return resolved[cid]
    statics = tree.get("s")
    if isinstance(statics, int):
        if statics > 0:
            source = _find_component(
                str(statics), components[str(statics)], cache, components, resolved
            )
        else:
            source = cache[str(-statics)]
        result = _clone_merge(source, tree)
        result["s"] = source["s"]
    elif "s" in tree or cid not in cache:
        result = tree
    else:
        result = _clone_merge(cache[cid], tree)
    resolved[cid] = result
    return result


def _do_mutable_merge(target: _Tree, source: _Tree) -> None:
    if "k" in source:
        _merge_keyed(target, source)
        return
    for key, value in source.items():
        old = target.get(key)
        if _is_object(value) and "s" not in cast(_Tree, value) and _is_object(old):
            _do_mutable_merge(cast(_Tree, old), cast(_Tree, value))
        else:
            target[key] = value


def _merge_keyed(target: _Tree, source: _Tree) -> None:
    keyed = cast(_Tree, source["k"])
    entries = cast(_Tree, target["k"])
    for key, value in keyed.items():
        if key in ("kc", "km"):
            continue
        assert _is_object(value), "this server never sends keyed moves"
        entry = cast(_Tree, entries.setdefault(key, {}))
        _do_mutable_merge(entry, cast(_Tree, value))
    count = cast(int, keyed["kc"])
    for index in range(count, cast(int, entries["kc"])):
        entries.pop(str(index), None)
    entries["kc"] = count
    if source.get("stream"):
        target["stream"] = source["stream"]


def _clone_merge(old: _Tree, new: _Tree) -> _Tree:
    assert "k" not in new
    merged = {**old, **new}
    for key in merged:
        value = new.get(key)
        before = old.get(key)
        if _is_object(value) and "s" not in cast(_Tree, value) and _is_object(before):
            merged[key] = _clone_merge(cast(_Tree, before), cast(_Tree, value))
        elif key not in new and _is_object(before):
            merged[key] = _clone_merge(cast(_Tree, before), {})
    return merged


def _client_html(node: _Tree, cache: dict[str, _Tree]) -> str:
    statics = cast(list[str], node["s"])
    if "k" in node:
        entries = cast(_Tree, node["k"])
        count = cast(int, entries["kc"])
        html = "".join(
            _client_dynamics(cast(_Tree, entries[str(index)]), statics, cache)
            for index in range(count)
        )
        stream = cast(list[object] | None, node.get("stream"))
        if stream is not None:
            deletes = cast(list[object], stream[2])
            if count > 0 or deletes or len(stream) > 3:
                # The client prunes stream entries once it renders them.
                del node["stream"]
                node["k"] = {"kc": 0}
        return html
    return _client_dynamics(node, statics, cache)


def _client_dynamics(node: _Tree, statics: list[str], cache: dict[str, _Tree]) -> str:
    parts: list[str] = []
    for index, static in enumerate(statics[:-1]):
        parts.append(static)
        value = node[str(index)]
        if isinstance(value, int):
            parts.append(_client_html(cache[str(value)], cache))
        elif _is_object(value):
            parts.append(_client_html(cast(_Tree, value), cache))
        else:
            parts.append(cast(str, value))
    parts.append(statics[-1])
    return "".join(parts)


class _Client:
    """Apply wire payloads the way the official client does."""

    def __init__(self) -> None:
        self.tree: _Tree | None = None

    def apply(self, payload: _Tree) -> str:
        wire = json.loads(json.dumps(payload))
        self.tree = _client_merge(self.tree, wire)
        cache = cast(dict[str, _Tree], self.tree["c"])
        return _client_html(self.tree, cache)

    def prune(self, cids: list[int]) -> None:
        assert self.tree is not None
        cache = cast(dict[str, _Tree], self.tree["c"])
        for cid in cids:
            cache.pop(str(cid), None)


def _component(cid: int, statics: tuple[str, ...], *values: str) -> _ComponentRendered:
    return _ComponentRendered(statics, values, cid)


def _stream(
    ref: str,
    inserts: tuple[_StreamInsert, ...] = (),
    deletes: tuple[str, ...] = (),
    *,
    reset: bool = False,
) -> _StreamRendered:
    return _StreamRendered(
        "".join(insert.html for insert in inserts), ref, inserts, deletes, reset
    )


def _insert(item_id: str, html: str) -> _StreamInsert:
    return _StreamInsert(item_id, html, -1, None)


_PAGE = ("<main>", "<p>", "</p>", "</main>")
_CARD = ('<div class="card">', "</div>")
_BADGE = ("<b>", "</b>")


def test_join_sends_the_whole_tree_and_title() -> None:
    state = _RenderState()
    payload = state.encode(Rendered(_PAGE, ("a", "b", "c")), "Home")
    assert payload == {"s": list(_PAGE), "0": "a", "1": "b", "2": "c", "t": "Home"}


def test_unchanged_render_sends_nothing() -> None:
    state = _RenderState()
    state.encode(Rendered(_PAGE, ("a", "b", "c")), None)
    assert state.encode(Rendered(_PAGE, ("a", "b", "c")), None) == {}


def test_changed_values_travel_without_statics() -> None:
    state = _RenderState()
    state.encode(Rendered(_PAGE, ("a", "b", "c")), None)
    assert state.encode(Rendered(_PAGE, ("a", "x", "c")), None) == {"1": "x"}


def test_nested_trees_with_the_same_statics_send_only_their_changes() -> None:
    state = _RenderState()
    before = Rendered(_PAGE, ("a", Rendered(_BADGE, ("1",)), "c"))
    after = Rendered(_PAGE, ("a", Rendered(_BADGE, ("2",)), "c"))
    state.encode(before, None)
    assert state.encode(after, None) == {"1": {"0": "2"}}


def test_nested_trees_with_new_statics_replace_the_cached_node() -> None:
    state = _RenderState()
    state.encode(Rendered(_PAGE, ("a", Rendered(_BADGE, ("1",)), "c")), None)
    replaced = Rendered(_PAGE, ("a", Rendered(_CARD, ("1",)), "c"))
    assert state.encode(replaced, None) == {"1": {"s": list(_CARD), "0": "1"}}
    # A plain value at a nested tree's position replaces it too.
    assert state.encode(Rendered(_PAGE, ("a", "1", "c")), None) == {"1": "1"}


def test_title_travels_only_when_it_changes() -> None:
    state = _RenderState()
    page = Rendered(_PAGE, ("a", "b", "c"))
    assert state.encode(page, None)["t"] == ""
    assert state.encode(page, "One") == {"t": "One"}
    assert state.encode(page, "One") == {}
    assert state.encode(page, None) == {"t": ""}


def test_unchanged_components_stay_cached_and_changed_ones_send_changes() -> None:
    state = _RenderState()
    state.encode(
        Rendered(_PAGE, (_component(1, _CARD, "x"), _component(2, _CARD, "y"), "")),
        None,
    )
    changed = Rendered(
        _PAGE, (_component(1, _CARD, "x"), _component(2, _CARD, "z"), "")
    )
    assert state.encode(changed, None) == {"c": {"2": {"0": "z"}}}
    swapped = Rendered(
        _PAGE, (_component(2, _CARD, "z"), _component(1, _CARD, "x"), "")
    )
    assert state.encode(swapped, None) == {"0": 2, "1": 1}


def test_component_templates_share_statics_within_a_diff() -> None:
    state = _RenderState()
    payload = state.encode(
        Rendered(_PAGE, (_component(1, _CARD, "x"), _component(2, _CARD, "y"), "")),
        None,
    )
    assert payload["c"] == {
        "1": {"s": list(_CARD), "r": 1, "0": "x"},
        "2": {"s": 1, "r": 1, "0": "y"},
    }


def test_new_components_share_statics_with_kept_cached_components() -> None:
    state = _RenderState()
    state.encode(Rendered(_PAGE, (_component(1, _CARD, "x"), "", "")), None)
    payload = state.encode(
        Rendered(_PAGE, (_component(1, _CARD, "x"), _component(2, _CARD, "y"), "")),
        None,
    )
    assert payload == {"1": 2, "c": {"2": {"s": -1, "r": 1, "0": "y"}}}


def test_components_left_out_of_a_render_do_not_lend_statics() -> None:
    # The client may prune a component the render left out before it applies
    # a deferred diff, so its cached statics are not referenced.
    state = _RenderState()
    state.encode(Rendered(_PAGE, (_component(1, _CARD, "x"), "", "")), None)
    payload = state.encode(Rendered(_PAGE, ("", _component(2, _CARD, "y"), "")), None)
    assert payload == {
        "0": "",
        "1": 2,
        "c": {"2": {"s": list(_CARD), "r": 1, "0": "y"}},
    }


def test_revived_components_diff_against_the_cached_tree_until_destroyed() -> None:
    state = _RenderState()
    state.encode(Rendered(_PAGE, (_component(1, _CARD, "x"), "", "")), None)
    state.encode(Rendered(_PAGE, ("", "", "")), None)
    # Brought back before the client confirmed `cids_destroyed`.
    assert state.encode(Rendered(_PAGE, (_component(1, _CARD, "x"), "", "")), None) == {
        "0": 1
    }
    state.encode(Rendered(_PAGE, ("", "", "")), None)
    state.forget([1])
    assert state.encode(Rendered(_PAGE, (_component(1, _CARD, "x"), "", "")), None) == {
        "0": 1,
        "c": {"1": {"s": list(_CARD), "r": 1, "0": "x"}},
    }


def test_new_page_statics_resend_every_component_in_full() -> None:
    # The client drops its component cache when the page tree is replaced.
    state = _RenderState()
    state.encode(Rendered(_PAGE, (_component(1, _CARD, "x"), "", "")), None)
    payload = state.encode(
        Rendered(("<div>", "</div>"), (_component(1, _CARD, "x"),)), None
    )
    assert payload == {
        "s": ["<div>", "</div>"],
        "0": 1,
        "c": {"1": {"s": list(_CARD), "r": 1, "0": "x"}},
    }


def test_a_component_rendered_as_the_whole_page_is_wrapped() -> None:
    state = _RenderState()
    payload = state.encode(_component(1, _CARD, "x"), None)
    assert payload["s"] == ["", ""]
    assert payload["0"] == 1


def test_streams_travel_only_with_operations() -> None:
    state = _RenderState()
    item = _insert("item-1", '<li id="item-1">One</li>')
    state.encode(Rendered(_PAGE, ("a", _stream("items", (item,)), "c")), None)
    assert state.encode(Rendered(_PAGE, ("a", _stream("items"), "c")), None) == {}
    # Inserting the same item again still travels: operations are not state.
    again = state.encode(Rendered(_PAGE, ("a", _stream("items", (item,)), "c")), None)
    assert again == {
        "1": {
            "s": ["", ""],
            "k": {"kc": 1, "0": {"0": '<li id="item-1">One</li>'}},
            "stream": ["items", [["item-1", -1, None, None]], []],
        }
    }
    deleted = state.encode(
        Rendered(_PAGE, ("a", _stream("items", deletes=("item-1",)), "c")), None
    )
    assert deleted["1"] == {
        "s": ["", ""],
        "k": {"kc": 0},
        "stream": ["items", [], ["item-1"]],
    }
    reset = state.encode(
        Rendered(_PAGE, ("a", _stream("items", reset=True), "c")), None
    )
    assert reset["1"] == {
        "s": ["", ""],
        "k": {"kc": 0},
        "stream": ["items", [], [], True],
    }


_TEMPLATES: tuple[tuple[str, ...], ...] = (
    ("<i>", "</i>"),
    ("<em>", "|", "</em>"),
    ("<ul>", "", "", "</ul>"),
)
# One component template matches a plain template, so a position can switch
# between a component and a plain tree with the same statics.
_COMPONENT_TEMPLATES: tuple[tuple[str, ...], ...] = (
    ('<div class="a">', "</div>"),
    ('<div class="b">', ":", "</div>"),
    ("<i>", "</i>"),
)
_WORDS = ("", "a", "b", "<&>")


class _Renders:
    """Random renders over a small vocabulary, so values and templates recur."""

    def __init__(self, seed: int) -> None:
        self.random = random.Random(seed)
        self.alive = list(range(1, 7))
        self.next_cid = 7
        self.rendered: set[int] = set()
        self.next_item = 0

    def page(self) -> Rendered:
        self.rendered = set()
        # The page statics change now and then, replacing the client's tree.
        statics = _PAGE if self.random.random() < 0.8 else ("<body>", "", "</body>")
        return Rendered(statics, tuple(self.value(0) for _ in range(len(statics) - 1)))

    def value(self, depth: int) -> str | Rendered | _StreamRendered:
        kind = self.random.randrange(5 if depth < 2 else 1)
        if kind == 1:
            statics = self.random.choice(_TEMPLATES)
            return Rendered(
                statics,
                tuple(self.value(depth + 1) for _ in range(len(statics) - 1)),
            )
        if kind == 2:
            candidates = [cid for cid in self.alive if cid not in self.rendered]
            if candidates:
                cid = self.random.choice(candidates)
                self.rendered.add(cid)
                statics = self.random.choice(_COMPONENT_TEMPLATES)
                return _ComponentRendered(
                    statics,
                    tuple(self.value(depth + 1) for _ in range(len(statics) - 1)),
                    cid,
                )
        if kind == 3:
            return self.stream()
        return self.random.choice(_WORDS)

    def stream(self) -> _StreamRendered:
        operation = self.random.randrange(4)
        ref = self.random.choice(("left", "right"))
        if operation == 1:
            self.next_item += 1
            item_id = f"item-{self.next_item}"
            html = f'<li id="{item_id}">{self.random.choice(_WORDS)}</li>'
            return _stream(ref, (_insert(item_id, html),))
        if operation == 2:
            return _stream(ref, deletes=(f"item-{self.next_item}",))
        if operation == 3:
            return _stream(ref, reset=True)
        return _stream(ref)

    def destroyed(self) -> list[int]:
        """Destroy some components the last render left out, as the client asks."""
        left_out = [cid for cid in self.alive if cid not in self.rendered]
        destroyed = [cid for cid in left_out if self.random.random() < 0.3]
        for cid in destroyed:
            # A destroyed CID never comes back; its identity mounts anew.
            self.alive.remove(cid)
            self.alive.append(self.next_cid)
            self.next_cid += 1
        return destroyed


@pytest.mark.parametrize("seed", range(40))
def test_the_client_rebuilds_every_render_from_changed_only_diffs(seed: int) -> None:
    renders = _Renders(seed)
    state = _RenderState()
    client = _Client()
    for _ in range(30):
        page = renders.page()
        payload = state.encode(page, renders.random.choice((None, "A", "B")))
        assert client.apply(payload) == page.to_html()
        destroyed = renders.destroyed()
        state.forget(destroyed)
        client.prune(destroyed)
