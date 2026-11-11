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
