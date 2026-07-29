FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY config/gate0-policy.json /app/config/gate0-policy.json
COPY fixtures/safe-bootstrap.json /app/fixtures/safe-bootstrap.json

RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 moxadv \
    && mkdir -p /app/runs \
    && chown -R moxadv:moxadv /app/runs

USER moxadv

ENTRYPOINT ["mox-adv"]
