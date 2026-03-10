#!/bin/bash

echo "=== GPU Slice Device Plugin Verification ==="
echo

echo "1. Checking if device plugin pods are running..."
kubectl get pods -n kube-system -l app=gpu-slice-device-plugin -o wide

echo
echo "2. Checking device plugin logs..."
kubectl logs -n kube-system -l app=gpu-slice-device-plugin --tail=10

echo
echo "3. Verifying GPU slice resources are advertised..."
echo "Looking for 'example.com/gpu-slice: 6' in node allocatable resources:"
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpu_slices: .status.allocatable."example.com/gpu-slice"}'

echo
echo "4. Full allocatable resources per node:"
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, allocatable: .status.allocatable}'

echo
echo "5. Testing with a sample pod..."
kubectl apply -f test-pod.yaml
echo "Waiting for test pod to complete..."
kubectl wait --for=condition=complete pod/gpu-slice-test --timeout=60s || true

echo
echo "6. Test pod logs:"
kubectl logs gpu-slice-test || echo "Pod may still be running or failed"

echo
echo "7. Test pod status:"
kubectl get pod gpu-slice-test -o yaml | grep -A 10 -B 5 "example.com/gpu-slice"

echo
echo "8. Cleanup test pod:"
kubectl delete pod gpu-slice-test --ignore-not-found=true

echo
echo "=== Verification Complete ==="
echo "If you see 'example.com/gpu-slice: \"6\"' in step 3, the device plugin is working correctly!"