from __future__ import annotations

import re
from collections.abc import Callable
from string.templatelib import Template
from typing import Any, cast

import pytest
import tori_py_liveview_ui
from tori_py_liveview import html
from tori_py_liveview_ui import (
    breadcrumbs,
    icon,
    nav,
    nav_item,
    navbar,
    navigation,
    pagination,
    skip_link,
    steps,
    tab_links,
)
from tori_py_liveview_ui.navigation import _page_numbers

# Calls that break a helper's contract go through an untyped alias.
ui = cast(Any, tori_py_liveview_ui)


def _render(template: Template) -> str:
    return html(template).to_html()


def _icon(name: str) -> str:
    return _render(icon(cast(Any, name), size="sm"))


def test_navigation_family_is_explicit() -> None:
    assert navigation.__all__ == [
        "breadcrumbs",
        "nav",
        "nav_item",
        "navbar",
        "pagination",
        "skip_link",
        "steps",
        "tab_links",
    ]


def test_skip_link_targets_a_fragment() -> None:
    assert _render(skip_link()) == (
        '<a class="tori-ui-skip-link" href="#main">Skip to content</a>'
    )
    assert 'href="#shop-main"' in _render(skip_link(href="#shop-main", label="Skip"))
    with pytest.raises(ValueError, match="must be a fragment"):
        skip_link(href="/main")
    with pytest.raises(ValueError, match="must be a fragment"):
        skip_link(href="#")


def test_nav_item_marks_the_current_page_and_carries_an_icon_and_a_badge() -> None:
    assert _render(nav_item("Orders", href="/orders")) == (
        '<li class="tori-ui-nav__item"><a class="tori-ui-nav__link" href="/orders">'
        '<span class="tori-ui-nav__label">Orders</span></a></li>'
    )
    assert _render(
        nav_item(
            "Inbox", href="/inbox", live="navigate", current=True, icon="mail", badge=3
        )
    ) == (
        '<li class="tori-ui-nav__item"><a class="tori-ui-nav__link" href="/inbox" '
        'data-phx-link="redirect" data-phx-link-state="push" aria-current="page">'
        f'{_icon("mail")}<span class="tori-ui-nav__label">Inbox</span>'
        '<span class="tori-ui-nav__badge">3</span></a></li>'
    )


def test_nav_and_navbar_are_labeled_navigation_landmarks() -> None:
    assert _render(nav(["A", "B"], label="Sections")) == (
        '<nav aria-label="Sections"><ul class="tori-ui-nav tori-ui-nav--vertical">AB'
        "</ul></nav>"
    )
    assert "tori-ui-nav--horizontal" in _render(
        nav([], label="Sections", orientation="horizontal")
    )
    assert _render(navbar(brand="Shop", items="ITEMS", actions="ACT")) == (
        '<nav class="tori-ui-navbar" aria-label="Main">'
        '<div class="tori-ui-navbar__brand">Shop</div>'
        '<ul class="tori-ui-nav tori-ui-nav--horizontal">ITEMS</ul>'
        '<div class="tori-ui-navbar__actions">ACT</div></nav>'
    )
    assert _render(navbar(brand="Shop", label="Site")) == (
        '<nav class="tori-ui-navbar" aria-label="Site">'
        '<div class="tori-ui-navbar__brand">Shop</div></nav>'
    )


def test_breadcrumbs_link_the_ancestors_and_mark_the_current_page() -> None:
    assert _render(
        breadcrumbs([("Home", "/"), ("Orders", "/orders"), ("#42 <new>", None)])
    ) == (
        '<nav aria-label="Breadcrumb"><ol class="tori-ui-breadcrumbs">'
        '<li class="tori-ui-breadcrumbs__item">'
        '<a class="tori-ui-breadcrumbs__link" href="/">Home</a></li>'
        '<li class="tori-ui-breadcrumbs__item">'
        '<a class="tori-ui-breadcrumbs__link" href="/orders">Orders</a></li>'
        '<li class="tori-ui-breadcrumbs__item">'
        '<span aria-current="page">#42 &lt;new&gt;</span></li></ol></nav>'
    )
    live = _render(breadcrumbs([("Home", "/"), ("Here", "/here")], live="navigate"))
    assert live.count('data-phx-link="redirect"') == 1
    # The last item is the current page even when it has an href.
    assert '<span aria-current="page">Here</span>' in live


@pytest.mark.parametrize(
    ("page", "pages", "siblings", "expected"),
    [
        (1, 1, 1, [1]),
        (1, 5, 1, [1, 2, None, 5]),
        (3, 5, 1, [1, 2, 3, 4, 5]),
        (5, 10, 1, [1, None, 4, 5, 6, None, 10]),
        # A gap of one page shows that page instead of an ellipsis.
        (4, 10, 1, [1, 2, 3, 4, 5, None, 10]),
        (10, 10, 0, [1, None, 10]),
        (5, 9, 2, [1, 2, 3, 4, 5, 6, 7, 8, 9]),
    ],
)
def test_pagination_always_shows_the_ends_and_the_neighbors(
    page: int, pages: int, siblings: int, expected: list[int | None]
) -> None:
    assert _page_numbers(page, pages, siblings) == expected


def test_pagination_renders_links_from_an_href_pattern() -> None:
    result = _render(
        pagination(page=2, pages=3, href="/orders?page={page}", live="patch")
    )

    assert result.startswith(
        '<nav aria-label="Pagination"><ul class="tori-ui-pagination">'
        '<li><a class="tori-ui-pagination__control '
        'tori-ui-pagination__control--step" href="/orders?page=1" '
        'data-phx-link="patch" data-phx-link-state="push" '
        f'aria-label="Previous page">{_icon("chevron-left")}</a></li>'
    )
    assert (
        '<li><a class="tori-ui-pagination__control '
        'tori-ui-pagination__control--page" href="/orders?page=2" '
        'data-phx-link="patch" data-phx-link-state="push" aria-current="page">2</a>'
        "</li>"
    ) in result
    assert 'href="/orders?page=3"' in result
    assert "aria-disabled" not in result
    # At the first page the previous step is not a link.
    first = _render(pagination(page=1, pages=3, href="/orders?page={page}"))
    assert (
        '<li><span class="tori-ui-pagination__control '
        f'tori-ui-pagination__control--step" aria-disabled="true">'
        f"{_icon('chevron-left')}</span></li>"
    ) in first


def test_pagination_renders_buttons_that_push_the_page_number() -> None:
    result = _render(pagination(page=3, pages=3, event="page", target=2))

    assert (
        '<li><button type="button" class="tori-ui-pagination__control '
        'tori-ui-pagination__control--step" aria-label="Previous page" '
        f'phx-click="page" phx-target="2" phx-value-page="2">{_icon("chevron-left")}'
        "</button></li>"
    ) in result
    assert (
        '<button type="button" class="tori-ui-pagination__control '
        'tori-ui-pagination__control--page" aria-current="page" phx-click="page" '
        'phx-target="2" phx-value-page="3">3</button>'
    ) in result
    assert (
        'aria-label="Next page" disabled phx-click="page" phx-target="2" '
        'phx-value-page="4">'
    ) in result
    gapped = _render(pagination(page=5, pages=10, event="page"))
    assert (
        gapped.count('<span class="tori-ui-pagination__gap" aria-hidden="true">') == 2
    )


def test_steps_mark_completed_current_and_upcoming_stages() -> None:
    assert _render(
        steps(["Cart", ("Payment", "Card or invoice"), "Done"], current=2)
    ) == (
        '<ol class="tori-ui-steps" aria-label="Progress">'
        '<li class="tori-ui-steps__step tori-ui-steps__step--complete">'
        f'<span class="tori-ui-steps__marker">{_icon("check")}'
        '<span class="tori-ui-visually-hidden">Completed: </span></span>'
        '<span class="tori-ui-steps__text"><span class="tori-ui-steps__title">Cart'
        "</span></span></li>"
        '<li class="tori-ui-steps__step tori-ui-steps__step--current" '
        'aria-current="step"><span class="tori-ui-steps__marker">2</span>'
        '<span class="tori-ui-steps__text"><span class="tori-ui-steps__title">'
        'Payment</span><span class="tori-ui-steps__description">Card or invoice'
        "</span></span></li>"
        '<li class="tori-ui-steps__step tori-ui-steps__step--upcoming">'
        '<span class="tori-ui-steps__marker">3</span>'
        '<span class="tori-ui-steps__text"><span class="tori-ui-steps__title">Done'
        "</span></span></li></ol>"
    )
    finished = _render(steps(["A", "B"], current=3))
    assert finished.count("tori-ui-steps__step--complete") == 2
    assert "aria-current" not in finished


def test_tab_links_are_navigation_links_not_aria_tabs() -> None:
    result = _render(
        tab_links(
            [("Profile", "/settings"), ("Billing", "/settings/billing")],
            current="/settings/billing",
            label="Settings",
            live="navigate",
        )
    )

    assert result == (
        '<nav aria-label="Settings"><ul class="tori-ui-tab-links">'
        '<li><a class="tori-ui-tab-links__link" href="/settings" '
        'data-phx-link="redirect" data-phx-link-state="push">Profile</a></li>'
        '<li><a class="tori-ui-tab-links__link" href="/settings/billing" '
        'data-phx-link="redirect" data-phx-link-state="push" aria-current="page">'
        "Billing</a></li></ul></nav>"
    )
    assert "role=" not in result


@pytest.mark.parametrize(
    ("call", "error", "message"),
    [
        (lambda: ui.nav([], label=""), ValueError, "nav label cannot be empty"),
        (
            lambda: ui.nav([], label="N", orientation="diagonal"),
            ValueError,
            "nav orientation must be one of",
        ),
        (
            lambda: ui.nav_item("x", href="/a", current="yes"),
            TypeError,
            "nav item current must be a boolean",
        ),
        (
            lambda: ui.nav_item("x", href="/a", icon="unicorn"),
            ValueError,
            "nav item icon must be one of",
        ),
        (
            lambda: ui.nav_item("x", href="javascript:alert(1)"),
            ValueError,
            "unsafe URL scheme",
        ),
        (
            lambda: ui.nav_item("x", href="orders", live="patch"),
            ValueError,
            "nav item live href must be a root-relative path",
        ),
        (lambda: ui.breadcrumbs([]), ValueError, "breadcrumbs requires at least one"),
        (
            lambda: ui.breadcrumbs([("a",), ("b", None)]),
            TypeError,
            "breadcrumbs items must be (label, href) tuples",
        ),
        (
            lambda: ui.pagination(page=1, pages=3),
            ValueError,
            "pagination requires either an href or an event",
        ),
        (
            lambda: ui.pagination(page=1, pages=3, href="/a?p={page}", event="e"),
            ValueError,
            "pagination requires either an href or an event",
        ),
        (
            lambda: ui.pagination(page=1, pages=3, href="/orders"),
            ValueError,
            "pagination href must contain {page}",
        ),
        (
            lambda: ui.pagination(page=4, pages=3, event="e"),
            ValueError,
            "pagination page must be between 1 and 3",
        ),
        (
            lambda: ui.pagination(page=1, pages=0, event="e"),
            ValueError,
            "pagination pages must be between",
        ),
        (
            lambda: ui.pagination(page=1, pages=3, event="e", live="patch"),
            ValueError,
            "pagination live requires an href",
        ),
        (
            lambda: ui.pagination(page=1, pages=3, event="e", siblings=9),
            ValueError,
            "pagination siblings must be between",
        ),
        (lambda: ui.steps([], current=1), ValueError, "steps requires at least one"),
        (
            lambda: ui.steps(["a"], current=3),
            ValueError,
            "steps current must be between 1 and 2",
        ),
        (
            lambda: ui.steps([("a", "b", "c")], current=1),
            TypeError,
            "steps items must be strings or two-item tuples",
        ),
        (
            lambda: ui.tab_links([], current="/a", label="T"),
            ValueError,
            "tab links requires at least one item",
        ),
        (
            lambda: ui.tab_links([("A", "/a")], current="", label="T"),
            ValueError,
            "tab links current cannot be empty",
        ),
    ],
)
def test_navigation_helpers_reject_values_outside_their_contract(
    call: Callable[[], Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=re.escape(message)):
        call()
