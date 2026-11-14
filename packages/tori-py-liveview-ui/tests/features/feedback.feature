@browser
Feature: LiveView UI feedback in a real browser
  Alerts, busy regions, toasts, flash, and the connection status report what
  the page or the connection is doing.

  Scenario: Alerts are dismissed by the browser or by the page
    Given I open the gallery page "/feedback"
    When I click the "Dismiss" button in ".tori-ui-alert:has-text('Dismissible')"
    Then ".tori-ui-alert:has-text('Dismissible')" is hidden
    When I click the "Dismiss" button in ".tori-ui-alert:has-text('Page-owned')"
    Then ".tori-ui-alert:has-text('Page-owned')" is gone
    And "text=The page-owned alert is gone." is visible
    # The render that removed the second alert kept the first one hidden.
    And ".tori-ui-alert:has-text('Dismissible')" is hidden

  Scenario: A busy region is inert while it loads
    Given I open the gallery page "/feedback"
    Then ".tori-ui-busy" has "aria-busy" set to "false"
    When I click the "Toggle loading" button
    Then ".tori-ui-busy" has "aria-busy" set to "true"
    And the status in ".tori-ui-busy" shows "Loading reports"
    And ".tori-ui-busy__content" is inert
    When I click the "Toggle loading" button
    Then ".tori-ui-busy" has "aria-busy" set to "false"
    And ".tori-ui-busy__content" is not inert

  Scenario: A toast closes itself and tells the page
    Given I open the gallery page "/feedback"
    When I click the "Notify" button
    Then "#toast-1" is visible
    And "#toast-1" contains "Message 1 delivered."
    And "#open-toasts" shows "1"
    # While the pointer rests on it the countdown is paused.
    When I hover "#toast-1"
    And 2200 milliseconds pass
    Then "#toast-1" is visible
    When I hover "h1"
    Then "#toast-1" is gone within 4 seconds
    And "#open-toasts" shows "0"

  Scenario: The flash group shows and clears flash
    Given I open the gallery page "/feedback"
    When I click the "Flash error" button
    Then "#gallery-flash-error" shows "A flash of kind error."
    And "#gallery-flash-error" has "role" set to "alert"
    When I click the "Dismiss" button in "#gallery-flash-error"
    Then "#gallery-flash-error" is hidden
    # The flash is cleared on the server, so the next render does not bring
    # it back.
    When I click the "Toggle loading" button
    Then ".tori-ui-busy" has "aria-busy" set to "true"
    And "#gallery-flash-error" is gone
    When I click the "Flash info" button
    Then "#gallery-flash-info" shows "A flash of kind info."
    # Information closes itself.
    And "#gallery-flash-info" is gone within 8 seconds

  Scenario: The connection status shows while the client is disconnected
    Given I open the gallery page "/feedback"
    Then ".tori-ui-connection-status" is hidden
    When the client disconnects
    Then ".tori-ui-connection-status" is visible
    And ".tori-ui-connection-status" shows "Connection lost. Reconnecting."
    When the client connects again
    Then ".tori-ui-connection-status" is hidden
