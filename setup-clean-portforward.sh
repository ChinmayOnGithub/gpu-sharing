#!/bin/bash

echo "🔧 SETTING UP CLEAN PORT FORWARDING"
echo "==================================="

# Kill existing port forwards
echo "1. Killing existing port forwards..."
pkill -f "port-forward" 2>/dev/null || true
sleep 2

# Start clean port forwards (redirect output to log files)
echo "2. Starting clean port forwards..."

# HPA app port forward
nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/hpa-fractional-app 8003:8080 \
    >/tmp/pf-hpa.log 2>&1 &
HPA_PID=$!

sleep 2

# Custom app port forward  
nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/custom-fractional-app 8004:8080 \
    >/tmp/pf-custom.log 2>&1 &
CUSTOM_PID=$!

sleep 2

echo "✅ Port forwards started:"
echo "   HPA app: localhost:8003 (PID: $HPA_PID)"
echo "   Custom app: localhost:8004 (PID: $CUSTOM_PID)"
echo ""
echo "📝 Logs:"
echo "   HPA: /tmp/pf-hpa.log"
echo "   Custom: /tmp/pf-custom.log"
echo ""
echo "🧪 Test connectivity:"
curl -s http://localhost:8003/health >/dev/null && echo "✅ HPA app accessible" || echo "❌ HPA app not accessible"
curl -s http://localhost:8004/health >/dev/null && echo "✅ Custom app accessible" || echo "❌ Custom app not accessible"

echo ""
echo "🚀 Run clean demo:"
echo "   python3 demo-fractional-clean.py"
echo ""
echo "🛑 Stop port forwards:"
echo "   kill $HPA_PID $CUSTOM_PID"