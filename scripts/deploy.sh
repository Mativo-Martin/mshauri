#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Pulling latest changes ==="
git fetch origin
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git reset --hard "origin/${CURRENT_BRANCH}"

echo "=== Building and starting DB ==="
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d --wait db keycloak

echo "=== Running database migrations ==="
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

echo "=== Seeding database (idempotent) ==="
docker compose -f docker-compose.prod.yml run --rm api python scripts/seed.py

echo "=== Starting all services ==="
docker compose -f docker-compose.prod.yml up -d --remove-orphans

echo "=== Checking health ==="
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:80/health >/dev/null 2>&1 || curl -fsS https://mshauri.mativo.space/health >/dev/null 2>&1; then
    echo "Deployment healthy!"
    exit 0
  fi
  echo "Waiting for health endpoint... ($i/30)"
  sleep 2
done

echo "Health check failed!"
docker compose -f docker-compose.prod.yml logs --tail=50
exit 1
