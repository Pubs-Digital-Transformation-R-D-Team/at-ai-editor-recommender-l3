FROM python:3.12-slim-trixie AS base

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY uv.lock pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-install-project --no-dev
COPY README.md .env /app/
COPY src /app/src
COPY prompts /app/prompts
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-dev


FROM base
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8012

ENV HOST="0.0.0.0"
ENV PORT=8012

# Use ddtrace-run for automatic instrumentation
ENTRYPOINT ["ddtrace-run"]
CMD ["uvicorn", "at_ai_editor_recommender.app:app", "--host", "0.0.0.0", "--port", "8012"]
#CMD uvicorn at_ai_editor_recommender.app:app --host $HOST --port $PORT