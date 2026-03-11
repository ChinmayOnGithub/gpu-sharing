#!/bin/bash
set -e

echo "🔐 FIXING SCALER RBAC PERMISSIONS"
echo "================================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Checking current RBAC setup..."
echo "Current role:"
$K describe role custom-gpu-scaler 2>/dev/null || echo "No role found"

echo -e "\nCurrent service account:"
$K get pod -l app=custom-gpu-scaler -o yaml | grep serviceAccount || echo "No service account found"

echo -e "\n2. Applying ClusterRole and ClusterRoleBinding..."
$K apply -f fix-scaler-rbac.yaml

echo "3. Restarting scaler to pick up new permissions..."
$K rollout restart deployment/custom-gpu-scaler

echo "4. Waiting for rollout..."
$K rollout status deployment/custom-gpu-scaler --timeout=60s

echo "✅ RBAC fixed! Checking logs..."
echo ""
$K logs deployment/custom-gpu-scaler --tail=20