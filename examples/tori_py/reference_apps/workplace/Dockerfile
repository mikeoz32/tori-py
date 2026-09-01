FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpq5 curl ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN mkdir -p examples/tori_py/reference_apps/workplace/web/assets \
    && curl -fsSL -o /tmp/keycloak-js.tgz https://github.com/keycloak/keycloak-js/releases/download/26.2.4/keycloak-js-26.2.4.tgz \
    && echo "1e52998fd8f44dc15293df6af88f0bae57248e503617930067cb802ebe9665c9  /tmp/keycloak-js.tgz" | sha256sum -c - \
    && tar -xzf /tmp/keycloak-js.tgz -O package/lib/keycloak.js > examples/tori_py/reference_apps/workplace/web/assets/keycloak.js \
    && rm /tmp/keycloak-js.tgz
RUN curl -fsSL -o examples/tori_py/reference_apps/workplace/web/assets/lit-core.min.js \
      https://cdn.jsdelivr.net/gh/lit/dist@3.3.1/core/lit-core.min.js \
    && echo "a511976d328c8565dd9afb7ced1bbece82b2b40078c6e2fa69967aefade265f5  examples/tori_py/reference_apps/workplace/web/assets/lit-core.min.js" | sha256sum -c -
RUN uv sync --frozen --dev

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace
