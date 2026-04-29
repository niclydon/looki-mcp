FROM python:3.12-slim

RUN groupadd -r looki && useradd -r -g looki looki

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY looki_mcp ./looki_mcp
COPY assets ./assets
COPY main.py .

RUN chown -R looki:looki /app
USER looki

EXPOSE 3456

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3456/health')" || exit 1

CMD ["python", "main.py"]
