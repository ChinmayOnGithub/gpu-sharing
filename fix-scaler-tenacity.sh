#!/bin/bash
set -e

echo "🔧 FIXING SCALER TENACITY DEPENDENCY"
echo "===================================="

# Force rebuild with no cache to ensure tenacity is installed
echo "1. Rebuilding custom scaler with tenacity..."
docker build --no-cache -t custom-gpu-scaler:latest k8s/custom-scaler-image/

echo "2. Importing to k3s..."
docker save custom-gpu-scaler:latest | sudo k3s ctr images import -

echo "3. Restarting scaler deployment..."
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout restart deployment/custom-gpu-scaler

echo "4. Waiting for rollout..."
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout status deployment/custom-gpu-scaler --timeout=60s

echo "✅ Scaler fixed! Checking logs..."
echo ""
sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml logs deployment/custom-gpu-scaler --tail=20