#!/bin/bash
set -e

echo "🔧 FIXING SCALER CRASH"
echo "====================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Checking current scaler status..."
$K get pods -l app=custom-gpu-scaler

echo -e "\n2. Checking scaler logs..."
$K logs deployment/custom-gpu-scaler --tail=5 || echo "No logs available"

echo -e "\n3. Deleting crashed scaler pod to force restart..."
$K delete pods -l app=custom-gpu-scaler --force --grace-period=0

echo -e "\n4. Waiting for new pod..."
sleep 10

echo -e "\n5. Checking new pod status..."
$K get pods -l app=custom-gpu-scaler

echo -e "\n6. Checking new logs..."
sleep 5
$K logs deployment/custom-gpu-scaler --tail=10

echo -e "\n✅ If still crashing, the issue is RBAC permissions"
echo "Run: kubectl apply -f fix-scaler-rbac.yaml"