FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY ml_engine/requirements.txt /tmp/ml-engine-requirements.txt
RUN python -m pip install --no-cache-dir \
    -r /tmp/backend-requirements.txt \
    -r /tmp/ml-engine-requirements.txt

COPY backend ./backend
COPY config ./config
COPY ml ./ml

RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data/uploads /app/ml/artifacts/feature_tables /app/ml/models \
    && chown -R app:app /app /data

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os; from urllib.request import urlopen; urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/v1/health', timeout=3).read()"

CMD ["sh", "-c", "exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
