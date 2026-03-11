#!/bin/bash
set -e

echo "🔧 FIXING CUPY COMPATIBILITY AND REDEPLOYING"
echo "============================================="

# Kill existing port forwards
pkill -f "kubectl.*port-forward" || true
sleep 2

# Clean up and rebuild GPU app
echo "1. Rebuilding GPU app with CuPy fix..."
cd k8s/gpu-app-image
docker build -t gpu-fractional-app:latest .
docker save gpu-fractional-app:latest | sudo k3s ctr images import -
cd ../..

# Restart deployments to pick up new image
echo "2. Restarting deployments..."
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl rollout restart deployment hpa-fractional-app
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl rollout restart deployment custom-fractional-app

# Wait for pods to be ready
echo "3. Waiting for pods to restart..."
sleep 15

# Setup port forwarding again
echo "4. Setting up port forwarding..."
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl port-forward service/hpa-fractional-app 8003:8080 >/dev/null 2>&1 &
HPA_PF_PID=$!
sleep 2

sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl port-forward service/custom-fractional-app 8004:8080 >/dev/null 2>&1 &
CUSTOM_PF_PID=$!
sleep 2

echo "Port forwards: HPA=8003, Custom=8004 (PIDs: $HPA_PF_PID, $CUSTOM_PF_PID)"

# Test the fix
echo "5. Testing GPU work endpoint..."
sleep 5
if curl -s "http://localhost:8003/gpu-work?type=matmul&size=500" | grep -q "success"; then
    echo "✅ GPU app is working!"
else
    echo "❌ GPU app still has issues"
    curl -s "http://localhost:8003/gpu-work?type=matmul&size=500"
fi

echo ""
echo "🎉 READY TO RUN DEMO!"
echo "Run: python3 demo-fractional.py"
echo ""
echo "🛑 STOP PORT FORWARDS:"
echo "kill $HPA_PF_PID $CUSTOM_PF_PID"