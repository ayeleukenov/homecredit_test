
FROM python:3.11-slim

WORKDIR /app

COPY /backend-database-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY /shared /app/shared

COPY /backend-database-service/app/ /app/

EXPOSE 8001

CMD ["python", "main.py"]
