@browser
Feature: LiveView UI disclosure in a real browser
  Collapsible sections and browser-switched tabs keep their state in the
  browser across server renders; page-owned tabs follow the page.

  Scenario: Collapsible state belongs to the browser
    Given I open the gallery page "/disclosure"
    Then "#shipping" is not open
    When I click "summary" in "#shipping"
    Then "#shipping" is open
    When I click the "Render again" button
    Then "#renders" shows "1"
    And "#shipping" is open
    # Sections in one group close each other.
    And "#track" is open
    When I click "summary" in "#pay"
    Then "#pay" is open
    And "#track" is not open
    When I click the "Render again" button
    Then "#renders" shows "2"
    And "#pay" is open
    And "#track" is not open

  Scenario: Browser tabs switch without the page and follow the keyboard
    Given I open the gallery page "/disclosure"
    Then the "Profile" tab is selected
    And "#settings-panel-profile" is visible
    And "#settings-panel-security" is hidden
    When I click the "Security" tab
    Then the "Security" tab is selected
    And the "Security" tab has "tabindex" set to "0"
    And the "Profile" tab is not selected
    And the "Profile" tab has "tabindex" set to "-1"
    And "#settings-panel-security" is visible
    And "#settings-panel-profile" is hidden
    When I press "ArrowRight"
    Then the "Billing" tab is focused
    And the "Billing" tab is selected
    And "#settings-panel-billing" is visible
    When I press "ArrowRight"
    Then the "Profile" tab is focused
    When I press "End"
    Then the "Billing" tab is focused
    When I press "Home"
    Then the "Profile" tab is selected
    # A server render keeps the tab the visitor chose.
    When I click the "Billing" tab
    And I click the "Render again" button
    Then "#renders" shows "1"
    And the "Billing" tab is selected
    And "#settings-panel-billing" is visible
    And "#settings-panel-profile" is hidden

  Scenario: Page tabs render only the panel the page chose
    Given I open the gallery page "/disclosure"
    Then "#reports [role=tabpanel]" appears 1 time
    And "#reports [role=tabpanel]" shows "Daily: 42 orders."
    When I click the "Weekly" tab
    Then the "Weekly" tab is selected
    And "#reports [role=tabpanel]" appears 1 time
    And "#reports [role=tabpanel]" shows "Weekly: 310 orders."
    And "#reports [role=tabpanel]" has "aria-labelledby" set to "reports-tab-weekly"
    When I focus the "Weekly" tab
    And I press "ArrowRight"
    Then "#reports [role=tabpanel]" shows "Monthly: 1,280 orders."
