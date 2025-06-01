#!/bin/bash

set -e

host="redis"
port="6379"

until redis-cli -h "$host" -p "$port" ping > /dev/null 2>&1; do
  echo "Waiting for Redis to be ready at $host:$port..."
  sleep 1
done

echo "Redis is ready!"