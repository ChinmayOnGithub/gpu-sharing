#!/bin/bash
set -e

echo "🔧 COMPLETE SCALER FIX"
echo "====================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Delete old RBAC resources..."
$K delete role custom-gpu-scaler --ignore-not-found=true
$K delete rolebinding custom-gpu-scaler --ignore-not-found=true

echo "2. Apply updated deployment with ClusterRole..."
$K apply -f k8s/custom-fractional-scaler.yaml

echo "3. Rebuild scaler with fixed config..."
docker build --no-cache -t custom-gpu-scaler:latest k8s/custom-scaler-image/
docker save custom-gpu-scaler:latest | sudo k3s ctr images import -

echo "4. Restart scaler..."
$K rollout restart deployment/custom-gpu-scaler
$K rollout status deployment/custom-gpu-scaler --timeout=60s

echo "✅ Complete fix applied! Checking logs..."
sleep 5
$K logs deployment/custom-gpu-scaler --tail=20