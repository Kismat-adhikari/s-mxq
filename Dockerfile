FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the application
COPY . .

# Create necessary directories
RUN mkdir -p templates static

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Expose port (Railway will override this with $PORT)
EXPOSE 8000

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:$PORT/health || exit 1

# Create a startup script
RUN echo '#!/bin/bash\n\
echo "Starting application..."\n\
echo "PORT: $PORT"\n\
echo "Current directory: $(pwd)"\n\
echo "Files in current directory:"\n\
ls -la\n\
echo "Starting gunicorn..."\n\
exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --log-level info --access-logfile - --error-logfile - app:app\n\
' > /app/start.sh && chmod +x /app/start.sh

# Use the startup script
CMD ["/app/start.sh"]