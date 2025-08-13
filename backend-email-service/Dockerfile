# email-service/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmagic1 \
    libmagic-dev \
    # libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY /backend-email-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY /shared /app/shared

COPY /backend-email-service/app/ /app/

EXPOSE 8003

CMD ["python", "main.py"]
