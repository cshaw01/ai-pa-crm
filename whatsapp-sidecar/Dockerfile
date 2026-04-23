FROM node:20-alpine

# git is needed because Baileys pulls libsignal-node from GitHub
RUN apk add --no-cache git

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY src/ ./src/

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

CMD ["node", "src/server.js"]
