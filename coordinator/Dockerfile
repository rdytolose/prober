FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY coordinator ./coordinator
COPY prober ./prober
RUN pip install --upgrade pip && pip install .

EXPOSE 8080
ENV COORDINATOR_HOST=0.0.0.0 \
    COORDINATOR_PORT=8080

CMD ["python", "-m", "coordinator.main"]
