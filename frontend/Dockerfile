# Stage 1: build the React app
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
# npm ci is preferred in CI (requires lockfile). Use npm install here so the
# image builds even before a lockfile is committed. Once you run
# `npm install` locally and commit package-lock.json, switch back to npm ci.
RUN npm install
COPY . .
RUN npm run build

# Stage 2: serve built assets via nginx with API proxy config
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
