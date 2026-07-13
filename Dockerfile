FROM python:3.13-slim

ARG UV_VERSION=0.9.26

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
    && groupadd --gid 10001 flight-hunter \
    && useradd --uid 10001 --gid 10001 --create-home flight-hunter

COPY pyproject.toml uv.lock README.md ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN uv sync --frozen --no-dev

RUN mkdir -p /data \
    && chown -R flight-hunter:flight-hunter /app /data

ENV PATH="/app/.venv/bin:${PATH}"

USER 10001:10001

CMD ["uvicorn", "flight_hunter.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
