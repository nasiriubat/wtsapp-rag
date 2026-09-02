"""Structured logs and Prometheus-style metrics, stdlib only."""

import json
import logging
import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counters = defaultdict(float)
_latency = {"count": 0, "sum": 0.0, "buckets": defaultdict(int)}
BUCKETS = (0.5, 1, 2, 5, 10)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # uvicorn installs its own handlers; route them through ours so every line is JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def reset():
    with _lock:
        _counters.clear()
        _latency.update({"count": 0, "sum": 0.0, "buckets": defaultdict(int)})


def count(name, **labels):
    key = (name, tuple(sorted(labels.items())))
    with _lock:
        _counters[key] += 1


def observe_latency(seconds):
    with _lock:
        _latency["count"] += 1
        _latency["sum"] += seconds
        for b in BUCKETS:
            if seconds <= b:
                _latency["buckets"][b] += 1


def _fmt_labels(labels):
    return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""


def render():
    lines = []
    with _lock:
        for (name, labels), value in sorted(_counters.items()):
            lines.append(f"{name}{_fmt_labels(labels)} {value:g}")
        for b in BUCKETS:
            lines.append(f'ask_latency_seconds_bucket{{le="{b}"}} {_latency["buckets"][b]}')
        lines.append(f'ask_latency_seconds_bucket{{le="+Inf"}} {_latency["count"]}')
        lines.append(f"ask_latency_seconds_sum {_latency['sum']:g}")
        lines.append(f"ask_latency_seconds_count {_latency['count']}")
    return "\n".join(lines) + "\n"
