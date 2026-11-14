@browser
Feature: LiveView UI documents in a real browser
  UiLiveView documents load the package stylesheet and script from the
  application and run on the unchanged official Phoenix clients. The gallery
  example is the application under test.

  Scenario: A document loads its local assets and connects
    Given I open the gallery page "/?skin=rounded"
    Then the document links the package stylesheet once
    And the document loads the package script once
    And "html" has "data-tori-ui-skin" set to "rounded"
    And "body" has class "tori-ui-document"
    And the client uses the registered hooks
    When I click the "Primary" button
    Then "#clicks" shows "1"

  Scenario: Application hooks and package hooks both register
    # The gallery replaces globalThis.ToriLiveHooks from an inline body
    # script, after the package script has run.
    Given I open the gallery page "/"
    Then the hook "GalleryClock" is registered
    And the hook "ToriUiTheme" is registered
    And every registered hook except "GalleryClock" starts with "ToriUi"
    And "#clock" is not empty
    And "#gallery-theme [data-tori-ui-theme-value='auto']" is pressed

  Scenario: A stored theme is applied before the body renders
    Given I open the gallery page "/?theme=light"
    Then "html" has "data-tori-ui-theme" set to "light"
    When the browser stores the theme "dark"
    And I reload the page watching the theme the body starts with
    Then "html" has "data-tori-ui-theme" set to "dark"
    And the body started with the theme "dark"
    # A stored value that is not a theme is ignored.
    When the browser stores the theme "sepia"
    And I reload the page
    Then "html" has "data-tori-ui-theme" set to "light"

  Scenario Outline: Every gallery page has sound markup
    # IDs are unique, every control has an accessible name, every image has
    # alternative text, and every reference to another element's ID resolves.
    Given I open the gallery page "<path>"
    Then the markup audit finds no problems

    Examples:
      | path        |
      | /           |
      | /actions    |
      | /layout     |
      | /content    |
      | /display    |
      | /feedback   |
      | /disclosure |
      | /forms      |
      | /navigation |
      | /overlays   |
      | /ai         |
      | /chat       |

  Scenario Outline: Every page renders in each theme and skin
    Then every gallery page fits the viewport with the "<theme>" theme and the "<skin>" skin

    Examples:
      | theme | skin      |
      | light | editorial |
      | light | minimal   |
      | light | rounded   |
      | dark  | editorial |
      | dark  | minimal   |
      | dark  | rounded   |

  Scenario: Narrow screens do not scroll sideways
    Given the viewport is 390 by 800
    Then every gallery page keeps its main area within the viewport
