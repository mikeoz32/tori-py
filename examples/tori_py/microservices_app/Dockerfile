FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /workspace

COPY . .

RUN uv sync --frozen --dev

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace
