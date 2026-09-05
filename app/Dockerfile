FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# proxy-headers: behind a TLS-terminating proxy the session cookie must still
# be marked Secure, and the login lockout must see the real client address.
# Only the proxy's own address may set those headers: trusting "*" would let
# any client choose the address the lockout counts against.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers \
     --forwarded-allow-ips \"${TRUSTED_PROXY:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}\""]
