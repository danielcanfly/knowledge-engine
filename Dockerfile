FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 knowledge
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

RUN mkdir -p /var/lib/knowledge-engine/cache && \
    chown -R knowledge:knowledge /var/lib/knowledge-engine /app
USER knowledge

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/v1/health', timeout=3)"

CMD ["uvicorn", "knowledge_engine.api:app", "--host", "0.0.0.0", "--port", "8080"]
