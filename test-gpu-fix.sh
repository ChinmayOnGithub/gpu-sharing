#!/bin/bash
set -e

echo "🧪 TESTING GPU FIX WITH NVIDIA RUNTIME"
echo "======================================"

# Check if pods are running
echo "1. Checking pod status..."
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get pods -l app=hpa-fractional-app
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get pods -l app=custom-fractional-app

# Test GPU work endpoint
echo -e "\n2. Testing GPU work endpoint..."
if curl -s "http://localhost:8003/gpu-work?type=matmul&size=500" | grep -q "success"; then
    echo "✅ HPA GPU app is working!"
    curl -s "http://localhost:8003/gpu-work?type=matmul&size=500" | jq .
else
    echo "❌ HPA GPU app has issues:"
    curl -s "http://localhost:8003/gpu-work?type=matmul&size=500"
fi

echo -e "\n3. Testing custom GPU app..."
if curl -s "http://localhost:8004/gpu-work?type=matmul&size=500" | grep -q "success"; then
    echo "✅ Custom GPU app is working!"
    curl -s "http://localhost:8004/gpu-work?type=matmul&size=500" | jq .
else
    echo "❌ Custom GPU app has issues:"
    curl -s "http://localhost:8004/gpu-work?type=matmul&size=500"
fi

# Test CUDA availability in pod
echo -e "\n4. Testing CUDA in pod..."
POD=$(sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get pods -l app=hpa-fractional-app -o jsonpath='{.items[0].metadata.name}')
echo "Testing CUDA in pod: $POD"
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl exec $POD -- python3 -c "
import cupy as cp
print('CUDA available:', cp.cuda.is_available())
if cp.cuda.is_available():
    print('GPU count:', cp.cuda.runtime.getDeviceCount())
    print('GPU name:', cp.cuda.runtime.getDeviceProperties(0)['name'].decode())
"

echo -e "\n🎉 GPU TESTING COMPLETE!"
echo "If all tests pass, run: python3 demo-fractional.py"