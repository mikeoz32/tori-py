@browser
Feature: LiveView UI content in a real browser
  Content helpers render text; a code block offers its own code to the
  clipboard.

  Scenario: A code block copies its own code
    Given the clipboard is available
    And I open the gallery page "/content"
    When I click the "Copy" button in the first ".tori-ui-code-block"
    Then ".tori-ui-copy-button" in the first ".tori-ui-code-block" has "data-tori-ui-copied" set to ""
    And the clipboard starts with:
      """
      @live_view("/hello")
      """
    And the clipboard ends with:
      """
      return container(heading("Hello", level=1))
      """
