#!/bin/bash
set -e

max_attempts=30
attempt=1
delay=5

echo "Waiting for migrations to complete..."

while [ $attempt -le $max_attempts ]; do
  if python manage.py migrate --check >/dev/null 2>&1; then
    echo "Migrations are complete."
    exit 0
  else
    echo "Migrations not complete (attempt $attempt/$max_attempts). Retrying in $delay seconds..."
    sleep $delay
    attempt=$((attempt + 1))
  fi
done

echo "Timed out waiting for migrations after $max_attempts attempts."
exit 1