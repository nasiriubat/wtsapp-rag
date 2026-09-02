FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
# Baileys' peer deps (sharp, jimp, audio-decode) are for media. Text-only ingest
# does not need them, and sharp alone doubles the image size.
RUN npm ci --legacy-peer-deps --omit=dev
COPY *.js ./
CMD ["node", "index.js"]
