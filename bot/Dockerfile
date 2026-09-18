FROM python:3.12-slim

COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV BOT_DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data/media /app/data/jobs /app/data/cache

CMD ["python", "bot_app.py"]
