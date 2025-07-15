FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libmp3lame-dev \
    libavcodec-extra \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip freeze
RUN ffmpeg -version
RUN yt-dlp --version

# Copy rest of the application
COPY . .

# Create necessary directories
RUN mkdir -p templates static

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=development

# Expose port (Railway will override this with $PORT)
EXPOSE 8000

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:$PORT/health || exit 1

CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --log-level info --access-logfile - --error-logfile - app:app


