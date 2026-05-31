#!/bin/bash
echo "Waiting 10s..."
sleep 10

echo "=== DNS Test ==="
docker exec bim-backend python3 -c "
import socket
try:
    r = socket.getaddrinfo('google.com', 443)
    print('DNS OK:', r[0][4])
except Exception as e:
    print('DNS FAIL:', e)
"

echo ""
echo "=== Bridge API Test ==="
TOKEN=$(curl -sf -X POST http://localhost:3001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@bim.vn","password":"TestPass123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])' 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "Login failed"
  exit 1
fi
echo "Login OK"

RESP=$(curl -sN --max-time 120 -X POST http://localhost:3001/api/v1/chat \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"Thiết kế cầu dầm BTCT 30m, 3 nhịp, 2 làn xe","mode":"design"}' 2>&1)

echo ""
echo "=== Response (first 500 chars) ==="
echo "$RESP" | head -c 500
echo ""
echo ""

echo "=== Markers ==="
echo "$RESP" | grep -o '"structure_type"[^,}]*' | head -1 || echo "no structure_type"
echo "$RESP" | grep -o '"total_length"[^,}]*' | head -1 || echo "no total_length"
echo "$RESP" | grep -o '"num_spans"[^,}]*' | head -1 || echo "no num_spans"
echo "$RESP" | grep -o '"filename"[^,}]*' | head -1 || echo "no filename"

echo ""
echo "=== Backend Logs ==="
docker logs bim-backend --tail 10 2>&1

echo ""
echo "=== IFC Files ==="
docker exec bim-backend ls -la /app/data/ifc/ 2>&1
