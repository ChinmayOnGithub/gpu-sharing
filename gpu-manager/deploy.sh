#!/bin/bash

set -e

echo "=== Deploying GPU Manager ==="

echo "1. Building Docker image..."
docker build -t gpu-manager:latest .

echo "2. Deploying GPU Manager DaemonSet..."
kubectl apply -f gpu-manager-daemonset.yaml

echo "3. Waiting for GPU Manager to be ready..."
kubectl wait --for=condition=ready pod -l app=gpu-manager -n kube-system --timeout=60s

echo "4. Checking GPU Manager status..."
kubectl get pods -n kube-system -l app=gpu-manager -o wide

echo "5. Checking logs..."
kubectl logs -n kube-system -l app=gpu-manager --tail=20

echo "6. Testing API connectivity..."
# Get the service cluster IP
SERVICE_IP=$(kubectl get service gpu-manager-service -n kube-system -o jsonpath='{.spec.clusterIP}')
echo "GPU Manager API available at: http://$SERVICE_IP:5000"

# Test health endpoint
echo "Testing health endpoint..."
kubectl run test-gpu-manager --rm -i --restart=Never --image=curlimages/curl -- \
  curl -f http://gpu-manager-service.kube-system.svc.cluster.local:5000/health || echo "Health check failed - service may still be starting"

echo
echo "=== Deployment Complete ==="
echo "GPU Manager Service: gpu-manager-service.kube-system.svc.cluster.local:5000"
echo "Cluster IP: http://$SERVICE_IP:5000"
echo "Endpoints:"
echo "  GET  /health  - Health check"
echo "  GET  /status  - GPU status and allocation table"
echo "  POST /allocate - Allocate GPU slices"
echo "  POST /release  - Release GPU slices"