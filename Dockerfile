# EU AI Act assistant: FastAPI app, deployed on Railway.
# Build:  docker build -t el-chatbot .
# Run:    docker run -p 8000:8000 -e GEMINI_API_KEY=... el-chatbot
FROM python:3.12-slim

# uv, the project's package manager, pinned to the version used in development
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# dependencies first, so code changes do not reinstall them
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# run as a non-root user; the SQLite conversation store lives in data/ (reset on every deploy)
RUN useradd --create-home app && chown -R app /app
USER app

ENV PATH="/app/.venv/bin:$PATH"
# Railway injects PORT; bind 0.0.0.0 as its docs require
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
