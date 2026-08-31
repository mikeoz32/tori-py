FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN uv sync --frozen --dev

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace
