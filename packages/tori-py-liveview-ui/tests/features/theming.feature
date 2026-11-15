@browser
Feature: LiveView UI themes, modes, and skins in a real browser
  A theme is two palettes, the mode picks one of them, and a skin is the
  shape. Bundled definitions are in the package stylesheet; an application
  registers its own, and each of those is served as a stylesheet of its own.

  Scenario Outline: A bundled theme needs no stylesheet of its own
    Given I open the gallery page "/?theme=<theme>&mode=<mode>"
    Then "html" has "data-tori-ui-theme" set to "<theme>"
    And the document links 1 stylesheet
    And "body" has the "paper" of the "<theme>" theme in the "<mode>" mode as its background
    And "body" has the "ink" of the "<theme>" theme in the "<mode>" mode as its color

    Examples:
      | theme    | mode  |
      | paper    | light |
      | slate    | light |
      | slate    | dark  |
      | contrast | dark  |

  Scenario: An application theme is served, linked, and applied
    Given I open the gallery page "/?theme=orchid&mode=light"
    Then "html" has "data-tori-ui-theme" set to "orchid"
    And the document links the stylesheet of the "orchid" theme
    And the document links 2 stylesheets
    And "body" has the "paper" of the "orchid" theme in the "light" mode as its background
    And the "Primary" button has the "accent" of the "orchid" theme in the "light" mode as its background

  Scenario: The mode toggle switches the palette of an application theme
    Given I open the gallery page "/actions?theme=orchid&mode=light"
    When I click "#actions-mode [data-tori-ui-mode-value='dark']"
    Then "body" has the "paper" of the "orchid" theme in the "dark" mode as its background
    And "body" has the "ink" of the "orchid" theme in the "dark" mode as its color
    When I click "#actions-mode [data-tori-ui-mode-value='light']"
    Then "body" has the "paper" of the "orchid" theme in the "light" mode as its background

  Scenario: An application skin is served, linked, and applied
    Given I open the gallery page "/?skin=compact"
    Then "html" has "data-tori-ui-skin" set to "compact"
    And the document links the stylesheet of the "compact" skin
    And the "Primary" button has the style "border-top-left-radius" set to "8px"

  Scenario: A themed part of a page keeps its own theme and mode
    Given I open the gallery page "/themes?theme=paper&mode=light"
    Then "body" has the "paper" of the "paper" theme in the "light" mode as its background
    And "#preview-contrast-dark" has the "paper" of the "contrast" theme in the "dark" mode as its background
    And "#preview-contrast-dark" has the "ink" of the "contrast" theme in the "dark" mode as its color
    And "#preview-orchid-light" has the "paper" of the "orchid" theme in the "light" mode as its background
    And the "Primary" button in "#preview-orchid-dark" has the "accent" of the "orchid" theme in the "dark" mode as its background
    # The mode of the document changes; a part with a mode of its own does not.
    When I click "#gallery-mode [data-tori-ui-mode-value='dark']"
    Then "body" has the "paper" of the "paper" theme in the "dark" mode as its background
    And "#preview-orchid-light" has the "paper" of the "orchid" theme in the "light" mode as its background

  Scenario: A themed part of a page takes its own skin
    Given I open the gallery page "/themes"
    Then the "Save" button in "#skin-editorial" has the style "border-top-left-radius" set to "4.48px"
    And the "Save" button in "#skin-rounded" has the style "border-top-left-radius" set to "12px"
    And the "Save" button in "#skin-compact" has the style "border-top-left-radius" set to "8px"

  Scenario: The themes page reports the contrast of the current theme
    Given I open the gallery page "/themes?theme=slate"
    Then "#current-theme" shows "slate"
    And "#contrast-summary" contains "56 of 56 contrast requirements met by slate"
