#!/bin/bash
set -e

echo "🚀 RUNNING COMPLETE FRACTIONAL GPU SYSTEM"
echo "=========================================="

# Step 1: Clean any existing resources
echo "1. Cleaning existing resources..."
./clean-reset.sh

# Step 2: Build and deploy everything
echo -e "\n2. Building and deploying system..."
./build-and-deploy-all.sh

# Step 3: Wait for everything to be ready
echo -e "\n3. Waiting for system to be fully ready..."
sleep 30

# Step 4: Verify system status
echo -e "\n4. System Status Check:"
echo "Pods:"
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml get pods -o wide

echo -e "\nGPU Slices:"
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml describe node jade | grep "example.com/gpu-slice" || echo "No GPU slices found"

echo -e "\nTesting endpoints:"
curl -s "http://localhost:8003/gpu-work?type=matmul&size=500" | jq .cuda_enabled 2>/dev/null && echo "✅ HPA endpoint working" || echo "❌ HPA endpoint failed"
curl -s "http://localhost:8004/gpu-work?type=matmul&size=500" | jq .cuda_enabled 2>/dev/null && echo "✅ Custom endpoint working" || echo "❌ Custom endpoint failed"

# Step 5: Run the demo
echo -e "\n5. Ready to run demo!"
echo "================================"
echo "🎯 Everything is set up and ready!"
echo ""
echo "🧪 RUN THE DEMO:"
echo "   python3 demo-fractional.py"
echo ""
echo "📊 MONITOR SCALING:"
echo "   # Watch pods scale:"
echo "   sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml get pods -w"
echo ""
echo "   # Watch scaler decisions:"
echo "   sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml logs -l app=custom-gpu-scaler -f"
echo ""
echo "   # Watch GPU usage:"
echo "   watch nvidia-smi"
echo ""
echo "🛑 STOP SYSTEM:"
echo "   ./clean-reset.sh"