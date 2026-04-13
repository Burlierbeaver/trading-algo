# NLP / Signal — Design

**Date:** 2026-04-12
**Worktree:** `nlp-signal-processing-for-market-events`
**Component role in pipeline:** `RawEvent` → NLP/Signal → `Signal{ticker, score, magnitude, confidence, event_type}`

## 1. Purpose

Convert a `RawEvent` (news, filings, social posts, research notes — delivered by the `data-ingestion` worktree) into one or more `Signal` objects that downstream strategy/execution worktrees can consume. All ML/NLP complexity is isolated here: sibling worktrees see only the plain dataclasses.

## 2. Locked architectural decisions

| Area | Decision |
|---|---|
| Approach | **LLM-based extraction** (Claude) — no handcrafted ML pipeline. |
| Input | Unified `RawEvent` (schema owned by `data-ingestion` worktree; mirrored here). |
| Volume profile | ~1k–10k events/day, near-real-time. |
| Model | `claude-sonnet-4-6` — fast, cheap, structured-output-capable. |
| Cost strategy | Prompt caching on a frozen system prompt + bounded concurrency via `asyncio.Semaphore`. |
| Fan-out | One `Signal` per `(RawEvent, affected ticker)` — M&A yields two signals, a downgrade naming a supplier+customer yields two. |
| Score semantics | **Directional** `score ∈ [-1, +1]` **and separate** `magnitude ∈ [0, 1]`. |
| Confidence | LLM self-reported `confidence ∈ [0, 1]`. |
| Event taxonomy | Fixed 13-value enum (earnings_beat/miss, guidance_raise/cut, ma_target/acquirer, analyst_upgrade/downgrade, product_launch, regulatory, litigation, macro, other). |
| Interface | Pure async library. No internal DB/queue — transport belongs to sibling worktrees. |
| Language | Python 3.11+. |

## 3. Public surface

```python
from nlp_signal import NLPSignalProcessor, RawEvent, Signal

processor = NLPSignalProcessor()         # wraps anthropic.AsyncAnthropic
signals = await processor.process(event) # list[Signal]  (0..N per event)
batches = await processor.process_many(events)  # list[list[Signal]]
```

Also exported: `EventType`, `LLMSignal`, `LLMExtraction`, `NLPSignalError`, `ExtractionError`, `RefusalError`.

## 4. Data flow

```
RawEvent
  │
  ▼
build_user_message(title, body, source, published_at)  ──►  XML-tagged user content
  │
  ▼
client.messages.parse(
    model=claude-sonnet-4-6,
    system=[{text: SYSTEM_PROMPT, cache_control: ephemeral}],
    messages=[user content],
    output_format=LLMExtraction,
)
  │
  ▼
ParsedMessage.content[0].parsed_output  →  LLMExtraction{signals: [LLMSignal, ...]}
  │
  ▼
Signal.from_llm(each, source_event_id=event.id)  ──►  list[Signal]
```

- `stop_reason == "refusal"` → `RefusalError`.
- `parsed_output is None` on all text blocks → `ExtractionError`.
- Bounded concurrency via `asyncio.Semaphore(concurrency=10 default)`.

## 5. Prompt strategy

- **Frozen system prompt** (`prompts.SYSTEM_PROMPT`): taxonomy + scoring/magnitude/confidence rubrics + strict rules (fan out to every materially-affected ticker, don't invent tickers, return empty list for non-market events, never emit prose outside the schema). No f-strings, no timestamps — byte-identical across every call so the prompt cache hits.
- **Volatile user message**: event source, published_at, title, body in XML tags, followed by the extraction instruction.
- Structured output via `output_format=LLMExtraction` (a Pydantic model) — SDK validates automatically; malformed output raises before we touch it.

## 6. Module layout

```
src/nlp_signal/
  __init__.py      # re-exports public API
  models.py        # RawEvent, EventType, LLMSignal, LLMExtraction, Signal
  prompts.py       # SYSTEM_PROMPT (frozen), build_user_message()
  errors.py        # NLPSignalError, ExtractionError, RefusalError
  processor.py     # NLPSignalProcessor (process, process_many, _extract)

tests/
  conftest.py      # sample_earnings_event, sample_ma_event, sample_non_market_event
  test_models.py   # range validation, from_llm semantics
  test_prompts.py  # frozen-prompt invariants, taxonomy coverage, user-msg format
  test_processor.py # mocked AsyncAnthropic — fan-out, refusal, extraction, concurrency, cache_control
```

## 7. Testing

All tests run offline against a mocked `AsyncAnthropic`. 26 tests covering:

- Pydantic range bounds on score/magnitude/confidence.
- `Signal.from_llm` uppercases ticker and sets UTC timestamp.
- System prompt contains every `EventType` value and has no format placeholders / timestamps (cache safety).
- User message XML structure.
- Single-ticker extraction end-to-end.
- M&A fan-out yields both `MA_TARGET` and `MA_ACQUIRER` signals.
- Empty signal list for non-market events.
- Refusal → `RefusalError`.
- Missing `parsed_output` → `ExtractionError`.
- `process_many` dispatches concurrently.
- `cache_control: {type: ephemeral}` is set on the system block and `output_format=LLMExtraction` is passed.
- Custom model / max_tokens override.

## 8. Out of scope (owned elsewhere)

- Ingestion transport (REST/Kafka/webhook) — `data-ingestion` worktree.
- Signal persistence, deduping, and publishing — downstream worktree.
- Position sizing / strategy logic — `strategy-engine` worktree.
- Backtesting harness — separate worktree.
- Live API key management / secrets — env-based, resolved by `anthropic.AsyncAnthropic()` default.
