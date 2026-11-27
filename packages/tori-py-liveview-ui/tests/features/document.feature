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

  Scenario: Application hooks and Lit components coexist
    # The gallery replaces globalThis.ToriLiveHooks from an inline body
    # script, after the package script has run.
    Given I open the gallery page "/"
    Then the hook "GalleryClock" is registered
    And the component "tori-ui-mode" is registered
    And the UI does not register named application hooks
    And "#clock" is not empty
    And "#gallery-mode [data-tori-ui-mode-value='auto']" is pressed

  Scenario: A stored mode is applied before the body renders
    Given I open the gallery page "/?mode=light"
    Then "html" has "data-tori-ui-mode" set to "light"
    When the browser stores the mode "dark"
    And I reload the page watching the mode the body starts with
    Then "html" has "data-tori-ui-mode" set to "dark"
    And the body started with the mode "dark"
    # A stored value that is not a mode is ignored.
    When the browser stores the mode "sepia"
    And I reload the page
    Then "html" has "data-tori-ui-mode" set to "light"

  Scenario Outline: The mode picks the palette of the theme
    Given I open the gallery page "/?mode=<mode>"
    Then "body" has the style "background-color" set to "<paper>"
    And "body" has the style "color" set to "<ink>"

    Examples:
      | mode  | paper              | ink                |
      | light | rgb(242, 236, 223) | rgb(32, 32, 29)    |
      | dark  | rgb(25, 24, 22)    | rgb(244, 237, 223) |

  Scenario: The automatic mode follows the color scheme the browser prefers
    Given the browser prefers a dark color scheme
    And I open the gallery page "/?mode=auto"
    Then "body" has the style "background-color" set to "rgb(25, 24, 22)"
    And "body" has the style "color" set to "rgb(244, 237, 223)"

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
      | /themes     |

  Scenario Outline: Every page renders in each mode and skin
    Then every gallery page fits the viewport in the "<mode>" mode with the "<skin>" skin

    Examples:
      | mode  | skin      |
      | light | editorial |
      | light | minimal   |
      | light | rounded   |
      | dark  | editorial |
      | dark  | minimal   |
      | dark  | rounded   |

  Scenario: Narrow screens do not scroll sideways
    Given the viewport is 390 by 800
    Then every gallery page keeps its main area within the viewport
