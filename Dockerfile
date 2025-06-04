# Stage 1: build
FROM python:3.11.12-slim-bullseye AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install --no-install-recommends -y \
      gcc \
      libffi-dev \
      build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.11.12-slim-bullseye
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Stage 3. exec
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
