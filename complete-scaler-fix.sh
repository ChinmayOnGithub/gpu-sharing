#!/bin/bash
set -e

echo "🚀 COMPLETE SCALER FIX"
echo "====================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Apply correct RBAC permissions..."
$K apply -f fix-scaler-rbac-simple.yaml

echo "2. Delete crashed scaler pod..."
$K delete pods -l app=custom-gpu-scaler --force --grace-period=0 || echo "No pods to delete"

echo "3. Wait for new pod to start..."
sleep 15

echo "4. Check scaler status..."
$K get pods -l app=custom-gpu-scaler

echo -e "\n5. Check scaler logs (should work now)..."
$K logs deployment/custom-gpu-scaler --tail=15

echo -e "\n✅ SCALER SHOULD BE WORKING NOW!"
echo "If you see scaling logs, the fix worked."
echo "If still crashing, run: kubectl describe pod -l app=custom-gpu-scaler"