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
