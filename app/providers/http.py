import httpx

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def post(url, headers, body):
    # One retry on transport errors and 5xx. A 4xx is the provider's final word
    # on this request, so it raises straight away.
    for attempt in (1, 2):
        try:
            res = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
        except httpx.TransportError:
            if attempt == 2:
                raise
            continue
        if res.status_code >= 500 and attempt == 1:
            continue
        res.raise_for_status()
        return res.json()


def get(url, headers, params=None):
    res = httpx.get(url, headers=headers, params=params, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def merge(body, options):
    # Admin-supplied options are merged into the request body; a null value
    # removes a key. This is the escape hatch for provider-specific knobs
    # (thinking budgets, effort, max_completion_tokens) without a UI per knob.
    out = dict(body)
    for key, value in (options or {}).items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out
