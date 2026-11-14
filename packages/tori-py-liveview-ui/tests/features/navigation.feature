@browser
Feature: LiveView UI navigation in a real browser
  Navigation helpers render links and landmarks; live links patch the page
  without a new document, and the page owns the current item.

  Scenario: The skip link moves focus to the main area
    Given the viewport is 1200 by 800
    And I open the gallery page "/navigation"
    # It is off screen until the keyboard reaches it.
    Then the "Skip to content" link is not in the viewport
    When I press "Tab"
    Then the "Skip to content" link is focused
    And the "Skip to content" link is in the viewport
    When I press "Enter"
    Then "#gallery-main" is focused

  Scenario: The sidebar marks the current page across live navigation
    Given the viewport is 1200 by 800
    And I open the gallery page "/navigation"
    Then the "Navigation" link in the "Components" navigation has "aria-current" set to "page"
    When I click the "Layout" link in the "Components" navigation
    Then "h1" shows "Layout"
    And the "Layout" link in the "Components" navigation has "aria-current" set to "page"
    And the "Navigation" link in the "Components" navigation does not have "aria-current" set to "page"

  Scenario: Pagination and steps follow page state
    Given I open the gallery page "/navigation"
    Then the "Previous page" button in the first "Pagination" navigation is disabled
    And the "1" button in the first "Pagination" navigation has "aria-current" set to "page"
    When I click the "Next page" button in the first "Pagination" navigation
    Then "#result-page" shows "2"
    When I click the "12" button in the first "Pagination" navigation
    Then "#result-page" shows "12"
    And the "12" button in the first "Pagination" navigation has "aria-current" set to "page"
    And the "Next page" button in the first "Pagination" navigation is disabled
    And the "11" button in the first "Pagination" navigation is visible
    And the "5" button in the first "Pagination" navigation is gone
    And the second listitem in the "Progress" list has "aria-current" set to "step"
    And the first listitem in the "Progress" list contains "Completed:"
    When I click the "Continue" button
    Then the third listitem in the "Progress" list has "aria-current" set to "step"
    And the second listitem in the "Progress" list does not have "aria-current" set to "step"

  Scenario: Breadcrumbs and tab links navigate live
    Given I open the gallery page "/navigation"
    Then "text='Breadcrumbs'" in the "Breadcrumb" navigation has "aria-current" set to "page"
    And the "Navigation" link in the "Related pages" navigation has "aria-current" set to "page"
    When I click the "Content" link in the "Related pages" navigation
    Then "h1" shows "Content"
    And the document was not reloaded
