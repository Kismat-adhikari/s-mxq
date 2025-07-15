FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the application
COPY . .

# Optional: Ensure templates and static folders exist
RUN mkdir -p templates static

# Expose port (Railway will provide this via PORT env var)
EXPOSE $PORT

# Run the app using Gunicorn with proper configuration
CMD gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app