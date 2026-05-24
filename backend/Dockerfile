FROM python:3.11-slim

WORKDIR /app

# Force rebuild: 2024-05-23-v3
ARG CACHEBUST=3

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Debug: verify database.py content
RUN grep -n "checkfirst" app/models/database.py || echo "checkfirst not found!"

# Expose port (Railway uses dynamic PORT)
EXPOSE 8000

# Run the app using shell to expand PORT env variable
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
