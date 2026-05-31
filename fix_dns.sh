#!/bin/bash
# Fix Docker DNS
echo '{"dns": ["8.8.8.8", "1.1.1.1"]}' | sudo tee /etc/docker/daemon.json
sudo service docker restart || true
sleep 5
echo "Docker restarted"
docker info 2>&1 | grep -i dns || echo "No DNS info in docker info"

# Also fix WSL DNS
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
echo "nameserver 1.1.1.1" | sudo tee -a /etc/resolv.conf

# Test
echo "=== DNS test ==="
nslookup google.com 2>&1 | head -5 || echo "nslookup not available"
curl -sf https://google.com -o /dev/null -w "HTTP %{http_code}\n" --max-time 5 || echo "curl failed"
