FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3
WORKDIR /app
COPY package.json package-lock.json ./
# Baileys' peer deps (sharp, jimp, audio-decode) are for media. Text-only ingest
# does not need them, and sharp alone doubles the image size.
RUN npm ci --legacy-peer-deps --omit=dev
COPY *.js ./
COPY channels ./channels
# The WhatsApp session and the retry queue live on bind mounts; written as the
# unprivileged node user they stay yours on the host as well.
RUN mkdir -p auth_state data && chown -R node:node /app
USER node
# The sync loop touches this file every pass; a wedged process stops touching it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD sh -c 'test -n "$(find data -maxdepth 1 -name heartbeat -mmin -2)"'
CMD ["node", "index.js"]
