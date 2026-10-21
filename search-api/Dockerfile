FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY search_api.py filters.py facets.py graph_api.py pilot_api.py pilot_rag.py pilot_lexical.py auth.py users.py manage_users.py ./
# Stamp the deployed commit; /api/health reports it.
# compose passes this from $APP_VERSION (see docker-compose.yml build.args); the
# bare image defaults to "unknown" if built without the arg.
ARG APP_VERSION=unknown
ENV APP_VERSION=$APP_VERSION
# The users SQLite (accounts, invite list, saved items) lives on a mounted volume.
RUN mkdir -p /data
EXPOSE 8092
HEALTHCHECK --interval=20s --timeout=5s --retries=5 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8092/api/health')"
CMD ["uvicorn", "search_api:app", "--host", "0.0.0.0", "--port", "8092"]
