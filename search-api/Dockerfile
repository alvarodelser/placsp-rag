FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY search_api.py .
EXPOSE 8092
HEALTHCHECK --interval=20s --timeout=5s --retries=5 --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8092/api/health')"
CMD ["uvicorn", "search_api:app", "--host", "0.0.0.0", "--port", "8092"]
