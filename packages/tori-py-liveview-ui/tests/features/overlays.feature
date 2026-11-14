@browser
Feature: LiveView UI overlays in a real browser
  Modals, drawers, and confirmations are native dialogs. Menus and popovers
  open next to their buttons. Each is owned by the browser or by the page.

  Scenario: A browser-owned modal traps focus and returns it
    Given I open the gallery page "/overlays"
    Then the "Settings" dialog is hidden
    When I click the "Open settings" button
    Then the "Settings" dialog is visible
    And the "Settings" dialog has "aria-describedby" set to "settings-description"
    # The rest of the page is inert while the dialog is open.
    And "#settings" is modal
    # Focus starts inside, and Tab never reaches the page behind the dialog:
    # it stays inside or leaves the document for the browser's own controls.
    And the focus is inside "#settings"
    And pressing "Tab" 6 times never moves the focus to the page behind "#settings"
    When I press "Escape"
    Then the "Settings" dialog is hidden
    And the "Open settings" button is focused
    # The close button, the footer action, and a click outside close it too.
    When I click the "Open settings" button
    And I click the "Close" button in the "Settings" dialog
    Then the "Settings" dialog is hidden
    When I click the "Open settings" button
    And I click the "Done" button in the "Settings" dialog
    Then the "Settings" dialog is hidden
    When I click the "Open settings" button
    Then the "Settings" dialog is visible
    When I click the page at 5, 5
    Then the "Settings" dialog is hidden

  Scenario: A page-owned modal follows page state
    Given I open the gallery page "/overlays"
    Then "#editing" shows "no"
    When I click the "Edit profile" button
    Then the "Edit profile" dialog is visible
    And "#editing" shows "yes"
    # Escape asks the page to close it; the page answers by rendering it
    # closed.
    When I press "Escape"
    Then the "Edit profile" dialog is hidden
    And "#editing" shows "no"
    When I click the "Edit profile" button
    Then the "Edit profile" dialog is visible
    When I click the "Save" button in the "Edit profile" dialog
    Then the "Edit profile" dialog is hidden
    And "#editing" shows "no"

  Scenario: A drawer and a confirmation dialog
    Given I open the gallery page "/overlays"
    When I click the "Open filters" button
    Then the "Filters" dialog is visible
    When I click the "Apply" button in the "Filters" dialog
    Then the "Filters" dialog is hidden
    When I click the "Delete project" button
    Then the "Delete the project?" alertdialog is visible
    When I click the "Cancel" button in the "Delete the project?" alertdialog
    Then the "Delete the project?" alertdialog is hidden
    And "#deleted-projects" shows "0"
    When I click the "Delete project" button
    And I click the "Delete" button in the "Delete the project?" alertdialog
    Then "#deleted-projects" shows "1"
    And the "Delete the project?" alertdialog is hidden

  Scenario: A dropdown menu follows the keyboard and closes on a choice
    Given I open the gallery page "/overlays"
    Then the "Actions" menu is hidden
    When I click the "Actions" button
    Then the "Actions" menu is visible
    And the "Actions" button is expanded
    And the "Rename" menuitem in the "Actions" menu is focused
    When I press "ArrowDown"
    Then the "Duplicate" menuitem in the "Actions" menu is focused
    When I press "End"
    Then the "Delete" menuitem in the "Actions" menu is focused
    When I press "ArrowDown"
    Then the "Rename" menuitem in the "Actions" menu is focused
    When I press "Escape"
    Then the "Actions" menu is hidden
    And the "Actions" button is collapsed
    And the "Actions" button is focused
    When I click the "Actions" button
    And I click the "Duplicate" menuitem in the "Actions" menu
    Then "#last-action" shows "duplicate"
    And the "Actions" menu is hidden
    # A click outside closes it.
    When I click the "Actions" button
    Then the "Actions" menu is visible
    When I click "h1"
    Then the "Actions" menu is hidden

  Scenario: A popover opens next to its button
    Given I open the gallery page "/overlays"
    Then the "Keyboard shortcuts" dialog is hidden
    When I click the "Shortcuts" button
    Then the "Keyboard shortcuts" dialog is visible
    And the "Keyboard shortcuts" dialog is focused
    And the "Keyboard shortcuts" dialog contains "Press ? anywhere"
    When I press "Escape"
    Then the "Keyboard shortcuts" dialog is hidden
    And the "Shortcuts" button is focused
