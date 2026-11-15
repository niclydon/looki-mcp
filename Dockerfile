FROM python:3.12-slim

RUN groupadd -r looki && useradd -r -g looki looki

WORKDIR /app

COPY requirements.txt .
# TODO(OB-69924): consume the dependency lock here once it lands so the
# Docker route and the local install route do not drift apart.
RUN pip install --no-cache-dir -r requirements.txt

COPY looki_mcp ./looki_mcp
COPY assets ./assets
COPY main.py .

RUN chown -R looki:looki /app
USER looki

# EXPOSE documents the default port (3456); the runtime port is set by
# LOOKI_PORT and defaults to 3456 (see looki_mcp/config.py).
EXPOSE 3456

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+(os.environ.get('LOOKI_PORT') or '3456')+'/health')" || exit 1

CMD ["python", "main.py"]
