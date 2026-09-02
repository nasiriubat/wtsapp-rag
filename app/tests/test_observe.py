import json
import logging

import observe


def test_counters_and_latency_render_in_prometheus_text():
    observe.reset()
    observe.count("ingest_total")
    observe.count("ask_total", outcome="refused")
    observe.observe_latency(0.3)
    observe.observe_latency(3)
    text = observe.render()
    assert "# TYPE ingest_total counter" in text
    assert "ingest_total 1" in text
    assert 'ask_total{outcome="refused"} 1' in text
    assert 'ask_latency_seconds_bucket{le="0.5"} 1' in text
    assert 'ask_latency_seconds_bucket{le="5"} 2' in text
    assert "ask_latency_seconds_count 2" in text


def test_json_formatter_lifts_extra_fields_to_top_level():
    record = logging.makeLogRecord(
        {"name": "app", "levelno": logging.INFO, "levelname": "INFO", "msg": "ask", "latency_ms": 42}
    )
    line = json.loads(observe.JsonFormatter().format(record))
    assert line["msg"] == "ask"
    assert line["latency_ms"] == 42
    assert line["logger"] == "app"
