@browser
Feature: LiveView pages in a real browser
  Pages served by Tori Py LiveView run on the unchanged, pinned official
  Phoenix and Phoenix LiveView clients.

  Scenario: A connected page handles a click event
    Given I open the "/browser-counter" live page
    Then "#connection" shows "connected"
    And "#count" shows "0"
    When I click "#increment"
    Then "#count" shows "1"

  Scenario: push_navigate rejoins without reloading the document
    Given I open the "/browser-nav" live page
    And "#action" shows "index"
    When I click "#edit"
    Then the URL is "/browser-nav/edit"
    And "#action" shows "edit"
    And the document was not reloaded

  Scenario: A live redirect link rejoins without reloading the document
    Given I open the "/browser-nav" live page
    And "#action" shows "index"
    When I click "#anchor-edit"
    Then the URL is "/browser-nav/edit"
    And "#action" shows "edit"
    And the document was not reloaded

  Scenario: A hook pushes an event, receives the reply, and handles a server event
    Given I open the "/browser-hooks" live page
    Then "#pings" shows "1"
    And "#hooked" shows "42"
    And "#hooked" has "data-server" set to "pong 1"

  Scenario: Flash shows after an event and lv:clear-flash dismisses it
    Given I open the "/browser-flash" live page
    When I click "#save"
    Then "#flash-info" shows "Saved"
    When I click "#flash-info"
    Then "#flash-info" is empty

  Scenario: Flash follows push_navigate through the signed flash token
    Given I open the "/browser-flash" live page
    When I click "#navigate"
    Then the URL is "/browser-flash/next"
    And "#flash-info" shows "Moved"
    And the document was not reloaded

  Scenario: Flash follows a redirect through the Phoenix flash cookie
    Given I open the "/browser-flash" live page
    When I click "#leave"
    Then the URL is "/browser-flash/next"
    And "#flash-info" shows "Left"
    And the document was reloaded
    And the "__phoenix_flash__" cookie is gone

  Scenario: Flash passes through a page that navigates while mounting
    Given I open the "/browser-flash" live page
    When I click "#hop"
    Then the URL is "/browser-flash/next"
    And "#flash-info" shows "Hopped"
    And the document was not reloaded

  Scenario: Flash passes through a page that redirects during its HTTP render
    Given I open the "/browser-flash" live page
    When I click "#hop-reload"
    Then the URL is "/browser-flash/next"
    And "#flash-info" shows "Hopped over HTTP"
    And the document was reloaded
    And the "__phoenix_flash__" cookie is gone

  Scenario: assign_async renders a loading state and then its result
    Given I open the "/browser-async" live page
    Then "#org" shows "loading"
    When I click "#release"
    Then "#org" shows "Acme"

  Scenario: A connected mount reads the browser's connect params
    Given I open the "/browser-params" live page
    Then "#locale" shows "uk"
    And "#mounts" shows "0"
    And "#static-same" shows "unchanged"
    And "#static-new" shows "changed"
    When I click "#next"
    Then the URL is "/browser-params/next"
    And "#referer" shows the "/browser-params" URL

  Scenario: A reconnect URL carries application params but no join fields
    Given I open the "/browser-params" live page
    When I click "#next"
    And the client reconnects
    Then the reconnect URL carries "locale=uk" and no LiveView join fields
    And "#locale" shows "uk"
    And "#mounts" shows "1"

  Scenario: A client error from the connected mount reloads into that error once
    When I visit "/browser-gone" and it fails after connecting
    Then the document answered 200 and then 404
    And the "__phoenix_reload_status__" cookie is gone

  Scenario: An update sends only the values and title that changed
    Given I open the "/browser-diff" live page
    When I click "#bump"
    Then "#page-count" shows "1"
    And the last update was {"0": "1", "t": "Clicks 1"}
    And the page title is "Clicks 1"

  Scenario: A component update leaves its unchanged sibling untouched
    Given I open the "/browser-diff" live page
    And I mark "#left-card" and "#right-card"
    When I click "#left-bump"
    Then "#left-count" shows "1"
    And "#right-card" still has its mark
    And "#left-card" lost its mark
    And the last update was {"c": {"1": {"2": "1"}}}
    And the page title is "Clicks 0"

  Scenario: A component mounted again copies the statics of a cached one
    Given I open the "/browser-diff" live page
    When I click "#toggle"
    Then "#right-card" is gone
    And the server destroyed component 2
    When I click "#toggle"
    Then "#right-count" shows "0"
    And the last update gave component 3 the statics of component 1
    When I click "#right-bump"
    Then "#right-count" shows "1"

  Scenario: A component brought back before it is destroyed keeps its state
    Given I open the "/browser-diff" live page
    When I click "#right-bump"
    Then "#right-count" shows "1"
    When I click "#blink"
    Then the last update was {"2": 2}
    And "#right-count" shows "1"
    When I click "#right-bump"
    Then "#right-count" shows "2"

  Scenario: Stream items stay when updates leave the stream out
    Given I open the "/browser-diff" live page
    When I click "#add"
    Then "#items" lists 1 items
    When I click "#bump"
    Then "#page-count" shows "1"
    And "#items" lists 1 items
    When I click "#add"
    Then "#items" lists 2 items

  Scenario: A nested component handles its own events
    Given I open the "/browser-nested" live page
    And I mark "#branch" and "#leaf-b"
    When I click "#leaf-a-bump"
    Then "#leaf-a-count" shows "1"
    And "#branch" still has its mark
    And "#leaf-b" still has its mark
    And the last update was {"c": {"2": {"2": "1"}}}

  Scenario: Nested components leave with their parent
    Given I open the "/browser-nested" live page
    When I click "#leaf-a-bump"
    Then "#leaf-a-count" shows "1"
    When I click "#drop"
    Then "#leaf-b" is gone
    And the server destroyed component 3
    When I click "#toggle-tree"
    Then "#branch" is gone
    And the server destroyed component 1
    And the server destroyed component 2
    When I click "#toggle-tree"
    Then "#leaf-a-count" shows "0"
    And "#leaf-b-count" shows "0"
