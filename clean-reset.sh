#!/bin/bash

echo "🧹 CLEANING ALL FRACTIONAL GPU RESOURCES"
echo "========================================"

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

# Stop all port forwards
echo "1. Stopping port forwards..."
pkill -f "kubectl.*port-forward" || true
sleep 2

# Delete all deployments
echo "2. Deleting all deployments..."
$K delete deployment hpa-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete deployment custom-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete deployment custom-gpu-scaler --ignore-not-found=true --force --grace-period=0

# Delete all services
echo "3. Deleting all services..."
$K delete service hpa-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete service custom-fractional-app --ignore-not-found=true --force --grace-period=0

# Delete all HPAs
echo "4. Deleting HPAs..."
$K delete hpa hpa-fractional-autoscaler --ignore-not-found=true --force --grace-period=0

# Delete all test pods
echo "5. Deleting test pods..."
$K delete pod test-fractional-gpu --ignore-not-found=true --force --grace-period=0
$K delete pod test-simple-pod --ignore-not-found=true --force --grace-period=0
$K delete pod test-gpu-pod --ignore-not-found=true --force --grace-period=0
$K delete pods -l app=fractional-examples --ignore-not-found=true --force --grace-period=0

# Delete RBAC
echo "6. Deleting RBAC resources..."
$K delete serviceaccount custom-gpu-scaler --ignore-not-found=true --force --grace-period=0
$K delete role custom-gpu-scaler --ignore-not-found=true --force --grace-period=0
$K delete rolebinding custom-gpu-scaler --ignore-not-found=true --force --grace-period=0

# Keep DaemonSet running (it's the core component)
echo "7. Keeping DaemonSet running (core component)..."

# Wait for cleanup
echo "8. Waiting for cleanup to complete..."
sleep 10

# Show final status
echo "9. Final status:"
$K get all
echo ""
$K get pods -A | grep -E "(hpa|custom|fractional)" || echo "✅ All fractional GPU resources cleaned"

echo ""
echo "✅ CLEANUP COMPLETE!"
echo "DaemonSet kept running for GPU resource advertisement"
echo "Ready for fresh deployment with build-and-deploy-all.sh"