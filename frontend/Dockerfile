# Vite dev server for local use: `docker compose up` serves the app on :5173 and forwards /api to
# the api service.
FROM node:24-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
CMD ["npm", "run", "dev"]
