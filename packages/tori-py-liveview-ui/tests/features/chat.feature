@browser
Feature: LiveView UI chat and AI helpers in a real browser
  A chat page streams a reply into a LiveView stream while the browser owns
  the composer keys and the scroll position of the log.

  Scenario: The chat sends on Enter, streams the reply, and follows it
    Given the viewport is 1100 by 640
    And I open the gallery page "/chat"
    Then "text=What do you want to build?" is visible
    # An empty message is not sent.
    When I press "Enter" on the "Message" textbox
    Then "#messages" is gone
    # Shift+Enter breaks the line; Enter sends.
    When I fill the "Message" textbox with "First line"
    And I press "Shift+Enter" on the "Message" textbox
    And I type "second line" into the "Message" textbox
    Then the "Message" textbox has the value "First line\nsecond line"
    When I press "Enter" on the "Message" textbox
    Then "#turn-1-user .tori-ui-chat-message__body" shows "First line\nsecond line"
    And the "Message" textbox has the value ""
    And the "Message" textbox is focused
    # While the reply streams the form offers to stop instead of to send.
    And the "Stop" button is visible
    And "#turn-1-assistant .tori-ui-reasoning" is visible
    And "#turn-1-assistant .tori-ui-tool-call--done" is visible within 10 seconds
    And "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And "#turn-1-assistant" contains "The page owns the state"
    And the first ".tori-ui-code-block [class^='tori-ui-hl-']" in "#turn-1-assistant" is visible
    And "#turn-1-assistant" does not have "aria-busy" set to "true"
    And the "Send" button is enabled
    # The log followed the growing reply to its end.
    And the chat log is at its end

  Scenario: Stop ends the reply
    Given I open the gallery page "/chat"
    When I click the "Show me code" button
    Then "#turn-1-user" contains "Show me a small LiveView"
    When I click the "Stop" button
    Then "#turn-1-assistant" contains "Stopped."
    And the "Send" button is enabled
    And "#turn-1-assistant .tori-ui-sources" is gone
    # The conversation continues after a stopped reply.
    When I fill the "Message" textbox with "Again"
    And I press "Enter" on the "Message" textbox
    Then "#turn-2-user" contains "Again"

  Scenario: The chat log lets go when the visitor scrolls up
    Given the viewport is 1100 by 520
    And I open the gallery page "/chat"
    When I fill the "Message" textbox with "One"
    And I press "Enter" on the "Message" textbox
    Then "#turn-1-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And the "Jump to the latest message" button is hidden
    When I fill the "Message" textbox with "Two"
    And I press "Enter" on the "Message" textbox
    Then "#turn-2-assistant" is visible
    When I scroll the chat log to its start
    Then "#messages-scroller" has "data-tori-ui-unpinned" set to ""
    And the "Jump to the latest message" button is visible
    # The second reply keeps growing, and the log stays where the visitor is.
    And "#turn-2-assistant .tori-ui-sources__item" appears 2 times within 15 seconds
    And the chat log is at its start
    When I click the "Jump to the latest message" button
    Then the "Jump to the latest message" button is hidden
    And the chat log is at its end

  Scenario: Model output parts keep their browser state
    Given the clipboard is available
    And I open the gallery page "/ai"
    Then "#message-assistant .tori-ui-chat-message__body" contains "Streams keep rendered items in the browser."
    And the "Previous response" button is disabled
    And "#reasoning-done" is not open
    # The visitor opens a reasoning block; the next render leaves it open.
    When I click "summary" in "#reasoning-done"
    Then "#reasoning-done" is open
    When I click the "Next response" button
    Then "#message-assistant .tori-ui-chat-message__body" contains "A stream sends inserts and deletes"
    And ".tori-ui-response-branch__count" shows "2 / 3"
    And the "Previous response" button is enabled
    And "#reasoning-done" is open
    When I click the "Next response" button
    Then the "Next response" button is disabled
    # The copy action takes the message body, not its footer or its actions.
    When I click the "Copy" button in "#message-assistant"
    Then the clipboard starts with "Use a stream when the list is long"
    And the clipboard does not contain "Streams guide"
    # A streaming message tells assistive technology to wait.
    And "#message-streaming" has "aria-busy" set to "true"
    And the status in "#message-typing" shows "Writing a reply"

  Scenario: Suggestions, attachments, and Markdown
    Given I open the gallery page "/ai"
    When I click the "Summarize" button
    Then "#picked" shows "Summarize this page."
    And ".tori-ui-attachment__name" show "report.pdf", "notes.md"
    When I click the "Remove report.pdf" button
    Then ".tori-ui-attachment__name" show "notes.md"
    # Raw HTML in the source is text, and the link leaves without the opener.
    And ".tori-ui-prose" contains "Raw HTML such as <b>this</b> stays text."
    And ".tori-ui-prose b" is gone
    And the "link" link in ".tori-ui-prose" has "target" set to "_blank"
    And the "link" link in ".tori-ui-prose" has "rel" set to "noopener noreferrer nofollow"
    And the table in ".tori-ui-prose" is visible
    And "#tool-running" contains "Running"
    And ".tori-ui-tool-call__data" in "#tool-running" is hidden
    When I click "summary" in "#tool-running"
    Then ".tori-ui-tool-call__data" in "#tool-running" shows:
      """
      {"path": "tests/"}
      """
    And the listitem in the "Steps" list appears 4 times
