FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml requirements-linux.lock ./
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-linux.lock \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/vector_indexes /app/data/model_cache \
    && chown -R appuser:appuser /app/data

COPY backend/app ./backend/app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-build-isolation --no-deps . && pip check

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
