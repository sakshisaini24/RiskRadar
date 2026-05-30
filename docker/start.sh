#!/bin/sh
set -e

export PORT="${PORT:-10000}"

echo "[start] RiskRadar — PORT=$PORT"

# API (internal)
uvicorn api.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

# Next.js standalone (internal)
cd /app/frontend
HOSTNAME=127.0.0.1 PORT=3000 node server.js &
NEXT_PID=$!

# Wait until backends respond
for i in 1 2 3 4 5 6 7 8 9 10; do
  if wget -q -O /dev/null http://127.0.0.1:8000/health 2>/dev/null; then
    echo "[start] API ready"
    break
  fi
  sleep 2
done
sleep 5
echo "[start] Starting nginx on port $PORT"

# Nginx on Render's public PORT
envsubst '${PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
exec nginx -g 'daemon off;'
