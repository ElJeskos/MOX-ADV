FROM python:3.12-slim AS release-builder

WORKDIR /build

COPY packaging /build/packaging
COPY scripts/build_release_distributions.py /build/scripts/build_release_distributions.py
COPY requirements-release.txt /build/requirements-release.txt
COPY src /build/src
COPY config /build/config
COPY fixtures /build/fixtures
COPY openapi /build/openapi

RUN python -m pip install \
    --no-cache-dir \
    setuptools==75.8.2 \
    wheel==0.45.1 \
    && python scripts/build_release_distributions.py \
    --version 1.0.0 \
    --output-dir /wheelhouse \
    && python -m pip download \
    --only-binary=:all: \
    --dest /wheelhouse \
    -r requirements-release.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=release-builder /wheelhouse /wheelhouse
COPY config/gate0-policy.json /app/config/gate0-policy.json
COPY fixtures/safe-bootstrap.json /app/fixtures/safe-bootstrap.json

RUN python -m pip install \
    --no-cache-dir \
    --no-index \
    --find-links /wheelhouse \
    mox-adv-paired==1.0.0 \
    && python -m pip check \
    && rm -rf /wheelhouse

RUN useradd --create-home --uid 10001 moxadv \
    && mkdir -p /app/runs \
    && chown -R moxadv:moxadv /app/runs

USER moxadv

ENTRYPOINT ["mox-adv"]
