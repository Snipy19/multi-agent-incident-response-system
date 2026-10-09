# Production container for the FastAPI incident-response service.
# The image contains application code and public assets only; secrets and
# runtime databases are supplied through environment variables and volumes.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Build tools are needed for packages that do not provide a compatible wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY auth.py graph.py main.py state.py pytest.ini ./
COPY agents ./agents
COPY db ./db
COPY frontend ./frontend
COPY utils ./utils
COPY vectorstore ./vectorstore
COPY data ./data

# Run as an unprivileged user. The database directory is writable so the
# local SQLite development volume can be used without running as root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/', timeout=3)"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
