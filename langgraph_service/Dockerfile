# syntax=docker/dockerfile:1
FROM python:3.12-slim-trixie AS base

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Install dependencies
COPY langgraph_service/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# Copy service code and shared data
COPY langgraph_service/ /app/langgraph_service/
COPY fake_data.py /app/fake_data.py
COPY resilience.py /app/resilience.py

FROM base
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app
ENV PYTHONPATH="/app"

EXPOSE 8000

CMD ["uvicorn", "langgraph_service.callback_server:app", "--host", "0.0.0.0", "--port", "8000"]
