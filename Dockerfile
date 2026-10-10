# BlockCode in one image: the web editor, the engine, and R (so all three languages run).
# Works on any host that runs containers (Render, Railway, Fly.io, Cloud Run, a VPS):
#   docker build -t blockcode . && docker run -p 8000:8000 blockcode

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates python3 python3-pip \
      r-base-core r-cran-dplyr r-cran-readr r-cran-ggplot2 r-cran-stringr \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --break-system-packages "uv>=0.11,<0.12"
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY blockcode ./blockcode
RUN uv sync --frozen --no-dev --python /usr/bin/python3
COPY --from=web /web/dist ./web/dist
# Learners' code runs as this user, which can't change the app's files.
RUN useradd --create-home blockcode
USER blockcode
# Running free-typed "Code" blocks (arbitrary Python/R) is off by default, like everywhere else,
# so a public container is safe. On a trusted or otherwise sandboxed host, turn it back on with:
#   docker run -e BLOCKCODE_ALLOW_RAW_CODE=1 -p 8000:8000 blockcode
EXPOSE 8000
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn blockcode.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
