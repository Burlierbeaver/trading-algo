from __future__ import annotations

from datetime import datetime, timezone

from nlp_signal import RawEvent

from trading_algo.ingestion import JSONLIngestion, ListIngestion


def _raw(event_id: str) -> RawEvent:
    return RawEvent(
        id=event_id,
        source="t",
        published_at=datetime.now(timezone.utc),
        title="t",
        body="b",
    )


def test_list_source_yields_events_in_order():
    source = ListIngestion([_raw("a"), _raw("b"), _raw("c")])
    assert [e.id for e in source] == ["a", "b", "c"]


def test_jsonl_reads_events_skipping_blanks_and_comments(tmp_path):
    path = tmp_path / "events.jsonl"
    ts = datetime.now(timezone.utc).isoformat()
    path.write_text(
        "\n".join(
            [
                "# comment",
                "",
                f'{{"id":"e1","source":"s","published_at":"{ts}","title":"t1","body":""}}',
                f'{{"id":"e2","source":"s","published_at":"{ts}","title":"t2","body":""}}',
            ]
        )
    )

    events = list(JSONLIngestion(path))

    assert [e.id for e in events] == ["e1", "e2"]
