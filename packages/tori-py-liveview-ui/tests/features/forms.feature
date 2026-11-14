@browser
Feature: LiveView UI forms in a real browser
  Form controls are native elements: the browser holds what the visitor
  types and chooses, and the page validates and stores it.

  Scenario: Text fields validate through the page
    Given I open the gallery page "/forms"
    When I fill the "Name" textbox with "A"
    Then "#name-error" shows "Enter at least two characters."
    And the "Name" textbox has "aria-invalid" set to "true"
    And the "Name" textbox has "aria-describedby" set to "name-error"
    When I fill the "Name" textbox with "Ada"
    Then "#name-error" is gone
    And "#state-name" shows "Ada"
    And the "Name" textbox is focused
    And the "Name" textbox has the value "Ada"
    # Native bounds and suggestions come from the attributes.
    And the "Seats" spinbutton has "min" set to "1"
    And the "Seats" spinbutton has "max" set to "500"
    And "#city-options option" appears 5 times
    And the "City" combobox has "list" set to "city-options"
    When I click the "Save" button
    Then "#state-saved" shows "1"

  Scenario: Choice controls send what the visitor chose
    Given I open the gallery page "/forms"
    Then the "Team" radio in the "Plan" radiogroup is checked
    When I check the "Business" radio in the "Plan" radiogroup
    Then "#state-plan" shows "business"
    When I check the "Tips" checkbox in the "Email topics" group
    Then "#state-topics" shows "product, tips"
    When I uncheck the "Product news" checkbox in the "Email topics" group
    Then "#state-topics" shows "tips"
    # A segmented control is a radio group: the arrow keys move the choice.
    When I focus the "List" radio in the "Default view" radiogroup
    And I press "ArrowRight"
    Then the "Board" radio in the "Default view" radiogroup is checked
    And "#state-view" shows "board"
    And the "Notify me about replies" switch is checked
    When I click the "Notify me about replies" switch
    Then the "Notify me about replies" switch is not checked
    And "#state-notify" shows "off"
    When I select "viewer" and "admin" in the "Roles" listbox
    Then "#state-roles" shows "viewer, admin"
    When I focus the "Volume" slider
    And I press "ArrowRight"
    Then "#state-volume" shows "41"
    And ".tori-ui-slider__value" shows "41"

  Scenario: Search is debounced and filters on the server
    Given I open the gallery page "/forms"
    Then the "Search orders" searchbox has "phx-debounce" set to "150"
    When I type "comp" into the "Search orders" searchbox
    Then "#matches" shows "Compiler"
    And the "Search orders" searchbox has the value "comp"
