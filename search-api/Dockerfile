FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY search_api.py .
EXPOSE 8092
CMD ["uvicorn", "search_api:app", "--host", "0.0.0.0", "--port", "8092"]
