# syntax=docker/dockerfile:1
FROM python:3.12-slim-trixie AS base

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Install dependencies from the service-level pyproject.toml
COPY langgraph_service/pyproject.toml /app/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Copy service code and shared data
COPY langgraph_service/ /app/langgraph_service/
COPY fake_data.py /app/fake_data.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

FROM base
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 8000

ENV HOST="0.0.0.0"
ENV PORT=8000

CMD ["uvicorn", "langgraph_service.callback_server:app", "--host", "0.0.0.0", "--port", "8000"]
