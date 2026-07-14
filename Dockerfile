FROM python:3.12-slim

# Don't buffer stdout/stderr — logs show up live in `docker logs`
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (data/ excluded via .dockerignore — mounted as volume instead)
COPY . .

# SQLite lives here; mounted from host for persistence
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
