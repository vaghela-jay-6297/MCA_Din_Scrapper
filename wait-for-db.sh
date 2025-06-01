#!/bin/bash
# wait-for-db.sh

set -e

host="$POSTGRES_HOST"
port="$POSTGRES_PORT"
user="$POSTGRES_USER"
db="$POSTGRES_DB"

until pg_isready -h "$host" -p "$port" -U "$user" -d "$db"; do
  echo "Waiting for PostgreSQL to be ready at $host:$port..."
  sleep 1
done

echo "PostgreSQL is ready!"