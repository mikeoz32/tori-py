FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv
FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

COPY --from=uv /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    BENCHMARK_BASE_IMAGE=python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/benchmark-venv

WORKDIR /workspace/benchmarks

COPY packages/tori-py /workspace/packages/tori-py
COPY benchmarks/pyproject.toml benchmarks/uv.lock ./
COPY benchmarks/Dockerfile benchmarks/compose.yaml ./
COPY benchmarks/src ./src

RUN uv sync --frozen --no-dev
RUN install -d /results

ENTRYPOINT ["uv", "run", "--frozen", "--no-dev", "tori-py-benchmark"]
CMD ["--output", "/results/latest.json"]
