from datetime import datetime, timezone

from nlp_signal.models import EventType
from nlp_signal.prompts import SYSTEM_PROMPT, build_user_message


def test_system_prompt_is_frozen():
    # No format placeholders or timestamps that would bust the prompt cache.
    assert "{" not in SYSTEM_PROMPT
    assert "}" not in SYSTEM_PROMPT
    assert "2026-" not in SYSTEM_PROMPT


def test_system_prompt_covers_all_event_types():
    for event in EventType:
        assert event.value in SYSTEM_PROMPT, f"missing taxonomy entry: {event.value}"


def test_build_user_message_contains_fields():
    msg = build_user_message(
        title="Acme Corp Q3 earnings beat",
        body="Acme reported EPS of $1.20 vs $1.10 consensus.",
        source="reuters",
        published_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
    )
    assert "<event>" in msg
    assert "<source>reuters</source>" in msg
    assert "<title>Acme Corp Q3 earnings beat</title>" in msg
    assert "EPS of $1.20" in msg
    assert "2026-04-01T12:00:00+00:00" in msg


def test_build_user_message_handles_empty_body():
    msg = build_user_message(
        title="Headline only",
        body="",
        source="rss",
        published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    assert "<body>(no body)</body>" in msg
