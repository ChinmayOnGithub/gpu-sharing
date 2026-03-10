#!/bin/bash

echo "=== GPU Manager Deployment Verification ==="
echo

echo "1. Checking DaemonSet status..."
kubectl get daemonset gpu-manager -n kube-system -o wide

echo
echo "2. Checking pods..."
kubectl get pods -n kube-system -l app=gpu-manager -o wide

echo
echo "3. Checking service..."
kubectl get service gpu-manager-service -n kube-system

echo
echo "4. Checking pod logs..."
kubectl logs -n kube-system -l app=gpu-manager --tail=20

echo
echo "5. Verifying GPU device mount..."
kubectl exec -n kube-system -l app=gpu-manager -- ls -la /dev/nvidia0 || echo "GPU device not found"

echo
echo "6. Checking environment variables..."
kubectl exec -n kube-system -l app=gpu-manager -- env | grep -E "(GPU_TOTAL_MEMORY|API_PORT|NVIDIA_)"

echo
echo "7. Testing API health from within cluster..."
kubectl run health-check --rm -i --restart=Never --image=curlimages/curl -- \
  curl -f http://gpu-manager-service.kube-system.svc.cluster.local:5000/health

echo
echo "8. Testing API status from within cluster..."
kubectl run status-check --rm -i --restart=Never --image=curlimages/curl -- \
  curl -s http://gpu-manager-service.kube-system.svc.cluster.local:5000/status

echo
echo "9. Checking resource usage..."
kubectl top pods -n kube-system -l app=gpu-manager || echo "Metrics not available"

echo
echo "=== Verification Complete ==="
echo
echo "Expected results:"
echo "✓ DaemonSet should show 1/1 ready on GPU nodes"
echo "✓ Pods should be in Running state"
echo "✓ Service should have ClusterIP assigned"
echo "✓ Health check should return 200 OK"
echo "✓ Status should show GPU info and 6 available slices"