# Production container for the FastAPI incident-response service.
# The image contains application code and public assets only; secrets and
# runtime databases are supplied through environment variables and volumes.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt

COPY auth.py graph.py main.py state.py pytest.ini ./
COPY agents ./agents
COPY db ./db
COPY frontend ./frontend
COPY utils ./utils
COPY vectorstore ./vectorstore
# The prebuilt FAISS index is all the runtime retriever needs. Raw datasets
# remain in the repository for index rebuilding but do not belong in the app image.

# Run as an unprivileged user. The database directory is writable so the
# local SQLite development volume can be used without running as root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/', timeout=3)"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
