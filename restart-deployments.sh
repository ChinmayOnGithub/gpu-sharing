#!/bin/bash

echo "🔄 RESTARTING DEPLOYMENTS WITH FIXES"
echo "===================================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Restarting custom-fractional-app..."
$K rollout restart deployment/custom-fractional-app

echo "2. Restarting custom-gpu-scaler..."
$K rollout restart deployment/custom-gpu-scaler

echo "3. Waiting for rollouts..."
$K rollout status deployment/custom-fractional-app --timeout=60s
$K rollout status deployment/custom-gpu-scaler --timeout=60s

echo "✅ Deployments restarted!"

echo -e "\n4. Checking scaler logs..."
$K logs deployment/custom-gpu-scaler --tail=10