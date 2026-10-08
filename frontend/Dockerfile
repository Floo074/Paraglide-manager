# syntax=docker/dockerfile:1
# ── Étape 1 : build Vite ─────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Variables lues AU BUILD par Vite
ARG VITE_USE_MOCKS=false
ARG VITE_KK7_TILES_URL=
ARG VITE_KK7_TMS=true
ENV VITE_USE_MOCKS=$VITE_USE_MOCKS \
    VITE_KK7_TILES_URL=$VITE_KK7_TILES_URL \
    VITE_KK7_TMS=$VITE_KK7_TMS
RUN npm run build

# ── Étape 2 : service statique nginx + proxy /api → backend ─────────
FROM nginx:1.27-alpine
# Cible du proxy et résolveur DNS (127.0.0.11 = DNS interne de Docker).
# Résolution à la volée : nginx démarre même si le backend n'est pas encore là
# (le site bascule alors en données de démonstration).
ENV BACKEND_UPSTREAM=http://backend:8000 \
    NGINX_RESOLVER=127.0.0.11
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
