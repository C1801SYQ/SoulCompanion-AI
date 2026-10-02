# Optional Linux web-only deployment. Native Windows is the verified edge path.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
WORKDIR /app
COPY requirements-web.txt constraints-web.txt ./
RUN python -m pip install --no-cache-dir -r requirements-web.txt \
    && useradd --uid 10001 --create-home companion \
    && mkdir /data && chown companion:companion /data
COPY --chown=companion:companion config.py ./
COPY --chown=companion:companion emotion ./emotion
COPY --chown=companion:companion core ./core
COPY --chown=companion:companion reports ./reports
COPY --chown=companion:companion web ./web
USER companion
ENV SOULCOMPANION_DB=/data/emotional_db.sqlite SOULCOMPANION_APP_ENV=production
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["python", "-m", "web.app", "--host", "127.0.0.1", "--port", "8000"]
