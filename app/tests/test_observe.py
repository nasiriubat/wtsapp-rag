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
    assert "ingest_total 1" in text
    assert 'ask_total{outcome="refused"} 1' in text
    assert 'ask_latency_seconds_bucket{le="0.5"} 1' in text
    assert 'ask_latency_seconds_bucket{le="5"} 2' in text
    assert "ask_latency_seconds_count 2" in text


def test_json_formatter_emits_one_object_per_line():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    line = observe.JsonFormatter().format(record)
    assert json.loads(line)["msg"] == "hello world"
