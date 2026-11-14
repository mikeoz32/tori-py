@browser
Feature: A LiveView Kit chat page in a real browser
  ChatLiveView runs on the unchanged, pinned official Phoenix and Phoenix
  LiveView clients. The chat example is the application under test; its model
  is scripted, so it needs no key.

  Scenario: A message streams a full reply
    Given the viewport is 1100 by 640
    And I open a new conversation
    Then the page title is "Tori Assistant"
    And the document loads the UI stylesheet and script once
    And "text=What do you want to build?" is visible
    # An empty message is not sent.
    When I press "Enter" on the "Message" textbox
    Then "#chat-messages" is gone
    # Shift+Enter breaks the line; Enter sends.
    When I fill the "Message" textbox with "First line"
    And I press "Shift+Enter" on the "Message" textbox
    And I type "second line" into the "Message" textbox
    And I press "Enter" on the "Message" textbox
    Then "#turn-1-user .tori-ui-chat-message__body" shows "First line\nsecond line"
    And the "Message" textbox has the value ""
    # While the reply streams the form offers to stop instead of to send.
    And the "Stop" button is visible
    And "#turn-1-assistant .tori-ui-reasoning" is visible
    And "#turn-1-assistant .tori-ui-tool-call--done" is visible within 10 seconds
    And "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And "#turn-1-assistant" contains "The page owns the conversation"
    And the first ".tori-ui-code-block [class^='tori-ui-hl-']" in "#turn-1-assistant" is visible
    And "#turn-1-assistant .tori-ui-token-usage" contains "1.2k"
    And "#turn-1-assistant" does not have "aria-busy" set to "true"
    And the "Try again" button in "#turn-1-assistant" is gone
    And the "Send" button is enabled
    # The log followed the growing reply to its end.
    And the chat log is at its end

  Scenario: A reasoning block stays open while the reply grows
    Given I open a new conversation
    When I click the "What can you do?" button
    And I click "summary" in "#turn-1-assistant-reasoning-0"
    Then "#turn-1-assistant-reasoning-0" is open
    # Every flush renders the message again; the visitor's choice survives.
    And "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And "#turn-1-assistant-reasoning-0" is open

  Scenario: Stop ends the reply and retry writes it again
    Given I open a new conversation
    When I click the "Show me code" button
    Then "#turn-1-user" contains "Show me a small chat page."
    When I click the "Stop" button
    Then "#turn-1-assistant" contains "Stopped."
    And "#turn-1-assistant .tori-ui-sources" is gone
    And the "Send" button is enabled
    When I click the "Try again" button in "#turn-1-assistant"
    Then "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And "#turn-1-assistant" does not contain "Stopped."
    And the "Try again" button in "#turn-1-assistant" is gone
    # The retry rewrote the reply; it did not add a second one.
    And ".tori-ui-chat-message--assistant" appears 1 time

  Scenario: A failed reply is retried
    Given I open a new conversation
    When I click the "Fail once" button
    Then the alert in "#turn-1-assistant" contains "Something went wrong."
    # What the model raised is for the server log.
    And "#turn-1-assistant" does not contain "failed on purpose"
    And the "Send" button is enabled
    When I click the "Try again" button in "#turn-1-assistant"
    Then "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And the alert in "#turn-1-assistant" is gone
    And ".tori-ui-chat-message--assistant" appears 1 time

  Scenario: A failed reply stops offering retry after the next message
    Given I open a new conversation
    When I click the "Fail once" button
    Then the "Try again" button in "#turn-1-assistant" is visible
    When I fill the "Message" textbox with "Never mind"
    And I press "Enter" on the "Message" textbox
    Then "#turn-2-user" contains "Never mind"
    And the alert in "#turn-1-assistant" contains "Something went wrong."
    And the "Try again" button in "#turn-1-assistant" is gone
    And "#turn-2-assistant .tori-ui-sources__item" appears 2 times within 15 seconds

  Scenario: A reload restores the conversation
    Given I open a new conversation
    When I fill the "Message" textbox with "Remember this"
    And I press "Enter" on the "Message" textbox
    Then "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    When I open the conversation again
    Then "text=What do you want to build?" is gone
    And "#turn-1-user" contains "Remember this"
    And "#turn-1-assistant .tori-ui-sources__item" appears 2 times
    And ".tori-ui-chat-message--assistant" appears 1 time
    # The restored conversation goes on.
    When I fill the "Message" textbox with "And this"
    And I press "Enter" on the "Message" textbox
    Then "#turn-2-user" contains "And this"
    And "#turn-2-assistant .tori-ui-sources__item" appears 2 times within 15 seconds

  Scenario: A dropped connection ends the reply and the page recovers
    Given I open a new conversation
    When I click the "What can you do?" button
    Then "#turn-1-assistant .tori-ui-reasoning" is visible
    When the connection drops and the client rejoins
    # The new mount restores what the cut-off reply had written.
    Then "#turn-1-assistant" contains "Stopped." within 10 seconds
    And the "Send" button is enabled
    And ".tori-ui-chat-message--assistant" appears 1 time
    When I click the "Try again" button in "#turn-1-assistant"
    Then "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And "#turn-1-assistant" does not contain "Stopped."
