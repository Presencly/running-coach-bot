FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume for SQLite database
VOLUME ["/app/data"]

# Set database path to persist volume
ENV DATABASE_PATH=/app/data/coach.db

# Run the bot
CMD ["python", "bot.py"]
