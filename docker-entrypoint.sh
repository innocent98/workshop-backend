#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
while ! nc -z db 5432; do
  sleep 1
done
echo "PostgreSQL is ready!"

echo "Waiting for Redis to be ready..."
while ! nc -z redis 6379; do
  sleep 1
done
echo "Redis is ready!"

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
# Execute the command passed to the container (allows celery, uvicorn, etc.)
if [ $# -eq 0 ]; then
    # No command provided, use default uvicorn
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
else
    # Execute the provided command
    exec "$@"
fi
