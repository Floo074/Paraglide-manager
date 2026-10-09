# syntax=docker/dockerfile:1
# Backend Paraglide Manager : FastAPI servi par uvicorn sur le port 8000.
# Construction : docker build -t paraglide-backend backend/
# Exécution    : docker run --rm -p 8000:8000 --env-file backend/.env paraglide-backend
# Le fichier .env n'est JAMAIS copié dans l'image (clés passées à l'exécution uniquement).
FROM python:3.12-slim

# uv (gestionnaire de dépendances du projet), binaire officiel
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 1) dépendances seules (couche mise en cache tant que pyproject.toml / uv.lock ne changent pas)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) code de l'application et données locales (fichiers OpenAir éventuels dans data/airspaces/)
COPY app ./app
COPY data ./data
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_MODE=auto

# utilisateur non privilégié
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin paraglide \
    && chown -R paraglide:paraglide /app
USER paraglide

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
