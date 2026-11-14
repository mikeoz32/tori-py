@browser
Feature: LiveView UI data display in a real browser
  Tables, lists, and tags send their events to the page, which owns the
  order, the selection, and the items. A tooltip is the browser's.

  Scenario: Table sorting is owned by the page
    Given I open the gallery page "/display"
    Then "tbody td:first-child" in the "Orders" table show "Ada Lovelace", "Edsger Dijkstra", "Grace Hopper"
    And the "Customer" columnheader has "aria-sort" set to "ascending"
    And the "Total" columnheader has "aria-sort" set to "none"
    When I click the button in the "Customer" columnheader
    Then "tbody td:first-child" in the "Orders" table show "Grace Hopper", "Edsger Dijkstra", "Ada Lovelace"
    And the "Customer" columnheader has "aria-sort" set to "descending"
    When I click the button in the "Total" columnheader
    Then "tbody td:first-child" in the "Orders" table show "Edsger Dijkstra", "Grace Hopper", "Ada Lovelace"
    And the "Total" columnheader has "aria-sort" set to "ascending"
    And the "Customer" columnheader has "aria-sort" set to "none"

  Scenario: List items and tags push their values
    Given I open the gallery page "/display"
    Then "#folder-inbox" has class "tori-ui-list-item tori-ui-list-item--selected"
    When I click the button in "#folder-starred"
    Then "#folder-starred" has class "tori-ui-list-item tori-ui-list-item--selected"
    And the button in "#folder-starred" has "aria-current" set to "true"
    And "#folder-inbox" has class "tori-ui-list-item"
    And ".tori-ui-tag--info .tori-ui-tag__label" show "python", "liveview", "phoenix"
    When I click the "Remove liveview" button
    Then ".tori-ui-tag--info .tori-ui-tag__label" show "python", "phoenix"
    When I click the "Upload more" button
    Then the "Upload" progressbar has "value" set to "50"

  Scenario: A tooltip opens on focus and Escape dismisses it
    Given I open the gallery page "/display"
    Then the tooltip is hidden
    When I focus ".tori-ui-tooltip"
    Then the tooltip is visible
    And the tooltip shows "Application programming interface"
    When I press "Escape"
    Then the tooltip is hidden
    # It opens again once the focus has left and come back.
    When I focus the "Upload more" button
    And I focus ".tori-ui-tooltip"
    Then the tooltip is visible
