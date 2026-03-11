#!/bin/bash
set -e

echo "🔧 FIXING IMMEDIATE ISSUES"
echo "========================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Check port forward logs..."
echo "HPA port forward log:"
cat /tmp/pf-hpa.log 2>/dev/null || echo "No HPA log"

echo -e "\nCustom port forward log:"
cat /tmp/pf-custom.log 2>/dev/null || echo "No Custom log"

echo -e "\n2. Kill existing port forwards..."
pkill -f "port-forward" 2>/dev/null || true
sleep 2

echo -e "\n3. Start new port forwards with proper kubeconfig..."
nohup sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/hpa-fractional-app 8003:8080 >/tmp/pf-hpa-new.log 2>&1 &
HPA_PID=$!
sleep 3

nohup sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/custom-fractional-app 8004:8080 >/tmp/pf-custom-new.log 2>&1 &
CUSTOM_PID=$!
sleep 3

echo "New port forwards: HPA=$HPA_PID, Custom=$CUSTOM_PID"

echo -e "\n4. Test connectivity..."
curl -s http://localhost:8003/health >/dev/null && echo "✅ HPA app accessible" || echo "❌ HPA app still not accessible"
curl -s http://localhost:8004/health >/dev/null && echo "✅ Custom app accessible" || echo "❌ Custom app still not accessible"

echo -e "\n5. Rebuild and restart scaler with fixed config..."
docker build --no-cache -t custom-gpu-scaler:latest k8s/custom-scaler-image/
docker save custom-gpu-scaler:latest | sudo k3s ctr images import -

echo -e "\n6. Restart scaler deployment..."
$K rollout restart deployment/custom-gpu-scaler
$K rollout status deployment/custom-gpu-scaler --timeout=60s

echo -e "\n7. Check scaler logs..."
sleep 5
$K logs deployment/custom-gpu-scaler --tail=10

echo -e "\n✅ FIXES APPLIED!"
echo "Port forwards: kill $HPA_PID $CUSTOM_PID"