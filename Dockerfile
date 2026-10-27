FROM python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f AS builder

WORKDIR /build
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2.0" "setuptools>=78.1.1" \
    && python -m pip install --no-cache-dir --target /opt/python -r requirements.txt \
    && PYTHONPATH=/opt/python python -c "import msgpack, urllib3; assert msgpack.version >= (1, 2, 1); assert tuple(map(int, urllib3.__version__.split('.'))) >= (2, 8, 0)"

FROM python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && python -m pip uninstall --yes pip setuptools
COPY --from=builder --chown=app:app /opt/python /opt/python
COPY --chown=app:app server.py .

ENV PYTHONPATH=/opt/python \
    TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000 \
    MCP_PATH=/mcp \
    KINDORA_MCP_URL=https://kindora-mcp.azurewebsites.net/mcp/

EXPOSE 8000
USER app
CMD ["python", "server.py"]
