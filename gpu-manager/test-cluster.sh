#!/bin/bash

echo "=== Testing GPU Manager in Cluster ==="

echo "1. Deploying test pod..."
kubectl apply -f test-pod-with-api.yaml

echo "2. Waiting for test pod to complete..."
kubectl wait --for=condition=complete pod/gpu-manager-test --timeout=60s || true

echo "3. Test pod logs:"
kubectl logs gpu-manager-test

echo "4. Cleanup test pod:"
kubectl delete pod gpu-manager-test --ignore-not-found=true

echo "5. Direct service test from cluster:"
kubectl run curl-test --rm -i --restart=Never --image=curlimages/curl -- \
  curl -s http://gpu-manager-service.kube-system.svc.cluster.local:5000/health

echo
echo "=== Cluster Test Complete ==="