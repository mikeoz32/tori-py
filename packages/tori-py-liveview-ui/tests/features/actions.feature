@browser
Feature: LiveView UI actions in a real browser
  Buttons send their events and values to the page, and the mode toggle,
  the confirmation, and the copy button keep their state in the browser.

  Scenario: The mode toggle applies, stores, and marks the choice
    Given I open the gallery page "/actions?mode=light"
    Then "#actions-mode [data-tori-ui-mode-value='light']" is pressed
    When I click "#actions-mode [data-tori-ui-mode-value='dark']"
    Then "html" has "data-tori-ui-mode" set to "dark"
    And "#actions-mode [data-tori-ui-mode-value='dark']" is pressed
    And "#actions-mode [data-tori-ui-mode-value='light']" is not pressed
    # Every toggle on the page follows the one that was used.
    And "#gallery-mode [data-tori-ui-mode-value='dark']" is pressed
    And the stored mode is "dark"
    # A server render leaves the browser-owned state alone.
    When I click the "Add 1" button
    Then "#total" shows "1"
    And "#actions-mode [data-tori-ui-mode-value='dark']" is pressed
    # The stored choice wins over the mode the server renders.
    When I reload the page
    Then "html" has "data-tori-ui-mode" set to "dark"
    And "#actions-mode [data-tori-ui-mode-value='dark']" is pressed

  Scenario: Event values and pressed state reach the page
    Given I open the gallery page "/actions"
    When I click the "Add 10" button
    And I click the "Add 1" button
    Then "#total" shows "11"
    And the "Favorite" button is not pressed
    When I click the "Favorite" button
    Then the "Favorite" button is pressed

  Scenario: A confirmation gates the click
    Given I open the gallery page "/actions"
    And confirmations will be dismissed and then accepted
    When I click the first "Delete" button
    And I click the "Add 1" button
    Then "#total" shows "1"
    And "#deleted" shows "0"
    When I click the first "Delete" button
    Then "#deleted" shows "1"
    And both confirmations asked "Delete the record?"

  Scenario: The copy button copies text and reports it
    Given the clipboard is available
    And I open the gallery page "/actions"
    When I click the "Copy token" button
    Then the "Copy token" button has "data-tori-ui-copied" set to ""
    And "[role=status]" in the "Copy token" button shows "Copied"
    And ".tori-ui-copy-button__done" in the "Copy token" button is visible
    And ".tori-ui-copy-button__idle" in the "Copy token" button is hidden
    And the clipboard holds "tori-ui-0042"
    # The report clears itself.
    And the "Copy token" button does not have "data-tori-ui-copied" set to "" within 4 seconds
    And "[role=status]" in the "Copy token" button is empty
