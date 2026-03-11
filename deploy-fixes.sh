#!/bin/bash
set -e

echo "🔧 DEPLOYING SCALING FIXES"
echo "=========================="

# Step 1: Build and import GPU app with fixed metrics
echo "1. Building fixed GPU app..."
docker build -t gpu-fractional-app:latest k8s/gpu-app-image/
echo "   Importing to k3s..."
docker save gpu-fractional-app:latest | sudo k3s ctr images import -

# Step 2: Build and import custom scaler with fixed logic
echo "2. Building fixed custom scaler..."
docker build -t custom-gpu-scaler:latest k8s/custom-scaler-image/
echo "   Importing to k3s..."
docker save custom-gpu-scaler:latest | sudo k3s ctr images import -

# Step 3: Restart deployments
echo "3. Restarting deployments..."
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout restart deployment/custom-fractional-app
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout restart deployment/custom-gpu-scaler

# Step 4: Wait for rollouts
echo "4. Waiting for rollouts to complete..."
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout status deployment/custom-fractional-app --timeout=120s
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout status deployment/custom-gpu-scaler --timeout=120s

echo "✅ Scaling fixes deployed!"
echo ""
echo "🔍 VERIFY SCALER LOGS:"
echo "sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml logs -f deployment/custom-gpu-scaler"
echo ""
echo "Should show:"
echo "✅ Good: GPU=18.3% REQS=4 RPS=22.1 SCORE=35"
echo "❌ Bad:  GPU=0.0% REQS=0 RPS=0.0 SCORE=0"