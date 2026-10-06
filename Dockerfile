FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY econ_calendar.json ./
# .env dipasang saat run (jangan bake secret ke image):
#   docker run -d --restart unless-stopped --env-file .env crypto-bot
CMD ["python", "-m", "src.runner", "--live", "--db", "/data/signals.db"]
