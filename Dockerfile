FROM python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app
COPY --chown=app:app requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2.0" \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app server.py .

ENV TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000 \
    MCP_PATH=/mcp \
    KINDORA_MCP_URL=https://kindora-mcp.azurewebsites.net/mcp/

EXPOSE 8000
USER app
CMD ["python", "server.py"]
