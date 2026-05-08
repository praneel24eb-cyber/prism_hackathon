FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Ensure memory directory exists
RUN mkdir -p memory

EXPOSE 8000

CMD ["python", "run.py"]
