FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY . .
# Nothing here needs root, and the models volume and the bind mounts should
# not end up root-owned on the host.
RUN adduser --system --group --home /app app && mkdir -p /models && chown -R app:app /app /models
USER app
# proxy-headers: behind a TLS-terminating proxy the session cookie must still
# be marked Secure, and the login lockout must see the real client address.
# Only the proxy's own address may set those headers: trusting "*" would let
# any client choose the address the lockout counts against.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${TRUSTED_PROXY:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}\""]
