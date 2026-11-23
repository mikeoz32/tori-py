"""The example application, driven without a browser."""

from __future__ import annotations

import pytest
from tori_py_liveview_kit import create_app

from examples.tori_py.liveview_kit.app import (
    AssistantLive,
    ConversationStore,
    ScriptedModel,
)

_RETRY = 'phx-click="chat:retry"'


@pytest.fixture(autouse=True)
def _instant_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ScriptedModel, "delay", 0.0)


async def _serve(serve):
    return await serve(
        create_app(AssistantLive, providers=(ScriptedModel, ConversationStore))
    )


async def _idle(channel) -> None:
    """Wait for the frame that offers to send again."""
    await channel.until(lambda: 'aria-label="Send"' in channel.sent_text(-1))


@pytest.mark.asyncio
async def test_the_example_streams_a_full_reply(serve) -> None:
    channel = (await _serve(serve)).channel("/")
    await channel.join()

    assert "What do you want to build?" in channel.document
    await channel.event("chat:send", {"message": "What is this?"})
    await _idle(channel)
    reply = channel.sent_text(-1)

    assert "The visitor asked: &#x27;What is this?&#x27;." in reply
    assert "tori-ui-tool-call--done" in reply
    assert "search_docs" in reply
    assert "turns one generator into a chat" in reply
    assert "tori-ui-code-block" in reply
    assert 'href="https://example.com/liveview-kit"' in reply
    assert "1.2k" in reply
    assert _RETRY not in reply


@pytest.mark.asyncio
async def test_the_example_fails_once_and_answers_on_retry(serve) -> None:
    channel = (await _serve(serve)).channel("/")
    await channel.join()

    await channel.event("chat:suggest", {"prompt": "Fail once, then answer on retry."})
    await _idle(channel)
    failed = channel.sent_text(-1)
    assert "Something went wrong." in failed
    assert "failed on purpose" not in channel.sent_text(0)
    assert _RETRY in failed

    await channel.event("chat:retry")
    await _idle(channel)
    retried = channel.sent_text(-1)
    assert "turns one generator into a chat" in retried
    assert "Something went wrong." not in retried
    assert _RETRY not in retried


@pytest.mark.asyncio
async def test_the_example_restores_a_conversation_by_its_name(serve) -> None:
    served = await _serve(serve)
    first = served.channel("/?conversation=notes")
    await first.join()
    await first.event("chat:send", {"message": "Remember this"})
    await _idle(first)
    await first.close()

    again = served.channel("/?conversation=notes")
    document = await again.get()
    assert "Remember this" in document
    assert "turns one generator into a chat" in document
    assert "What do you want to build?" not in document

    for other in ("/", "/?conversation=other", "/?conversation=not%20a%20name"):
        assert "Remember this" not in await served.channel(other).get()
