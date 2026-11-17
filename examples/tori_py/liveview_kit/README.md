# LiveView Kit Chat

A complete chat page on `tori-py-liveview-kit`. The model is scripted, so the
example needs no API key. Run it with:

```text
uv run python -m examples.tori_py.liveview_kit.app
```

Open `http://127.0.0.1:8000/`. To reload on a code change, run the same
application under an ASGI server instead:

```text
uv run uvicorn examples.tori_py.liveview_kit.app:application --reload
```

The page is one class. `respond()` yields what the model produces, and the kit
adds the history, the streamed reply, the stop button, the error display, and
retry. Choose **Fail once** to see a failed reply and retry it.

The example keeps conversations in memory through `initial_messages()` and
`reply_finished()`, so a reload shows the conversation again. Another name in
the query string opens another conversation: `/?conversation=notes`. A restart
of the server forgets them all.

`run_app()` generates a secret for the process and listens on the loopback
interface. Both are development defaults.

## Provider adapters

Two more files show how a real provider's stream becomes kit events. They are
examples to copy, not part of the package, and each needs its provider's SDK:

- `anthropic_adapter.py` maps the Anthropic Messages stream: text, summarized
  thinking, tool calls, web search results and citations, and usage.
- `openai_compatible_adapter.py` maps a Chat Completions stream, which is how
  local model servers such as Ollama, vLLM, and LM Studio are usually reached.

```python
@live_view("/")
class AssistantLive(ChatLiveView):
    def __init__(self, client: Annotated[AsyncAnthropic, Inject(AsyncAnthropic)]) -> None:
        self.client = client

    async def respond(self, messages):
        async for event in anthropic_events(self.client, messages):
            yield event
```

Both adapters run your own tools through a `run_tool(name, arguments)` function
you pass in. Their tests feed them stream events written in the wire format and
checked by each SDK's own models; neither has been run against a live API here.

## Browser scenarios

The example is the application under test for the `tori-py-liveview-kit`
pytest-bdd scenarios in `packages/tori-py-liveview-kit/tests/features/`. Install
Chromium once and run them:

```text
uv run playwright install chromium
uv run pytest packages/tori-py-liveview-kit/tests/test_browser.py
```

The scenarios drive the page through the real vendored official Phoenix and
Phoenix LiveView clients, and a scenario fails on any browser console error.
They cover sending, a streamed reply with reasoning, a tool call, sources, and
usage, stop, a failed reply followed by a successful retry, a reload that
restores the conversation, and a dropped connection.
