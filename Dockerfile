FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY fbar_api/ ./fbar_api/

# Expose application port
EXPOSE 8000

# Create non-root user and switch to it
RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

# Health check probing the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

# Run the application
CMD ["uvicorn", "fbar_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
