@browser
Feature: LiveView UI layout in a real browser
  The app shell shows its sidebar beside the content on wide screens and
  opens it over the content on narrow ones. The browser owns the open state.

  Scenario: The app shell shows the sidebar beside the content on wide screens
    Given the viewport is 1200 by 800
    And I open the gallery page "/"
    Then "#gallery-sidebar" is visible
    And ".tori-ui-app-shell__menu" is hidden
    # The shell fills the viewport and only its main area scrolls.
    And the document is 800 pixels tall
    And ".tori-ui-app-shell__main" has the style "overflow-y" set to "auto"

  Scenario: The app shell sidebar opens over the content on narrow screens
    Given the viewport is 480 by 800
    And I open the gallery page "/"
    Then "#gallery-sidebar" is hidden
    And the "Menu" button is collapsed
    When I click the "Menu" button
    Then "#gallery-sidebar" is visible
    And the "Menu" button is expanded
    # The browser keeps the open state across a server render. The scrim
    # covers the page, so a script presses the button behind it.
    When a script clicks the "Primary" button
    Then "#clicks" shows "1"
    And "#gallery-sidebar" is visible
    And the "Menu" button is expanded
    When I press "Escape"
    Then "#gallery-sidebar" is hidden
    And the "Menu" button is collapsed
    When I click the "Menu" button
    Then "#gallery-sidebar" is visible
    When I click ".tori-ui-app-shell__scrim" at 440, 400
    Then "#gallery-sidebar" is hidden

  Scenario: Live navigation keeps the document and closes the open sidebar
    Given the viewport is 480 by 800
    And I open the gallery page "/"
    When I click the "Menu" button
    Then "#gallery-sidebar" is visible
    When I click the "Layout" link in "#gallery-sidebar"
    Then the URL is "/layout?theme=auto&skin=editorial"
    And "h1" shows "Layout"
    And the document was not reloaded
    And "#gallery-sidebar" is hidden
    And the "Menu" button is collapsed
