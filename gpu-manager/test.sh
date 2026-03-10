#!/bin/bash

# Get GPU Manager API endpoint via service
API_URL="http://gpu-manager-service.kube-system.svc.cluster.local:5000"

echo "=== Testing GPU Manager API ==="
echo "API URL: $API_URL"
echo

echo "1. Health Check:"
curl -s "$API_URL/health" | jq '.'
echo

echo "2. Initial Status:"
curl -s "$API_URL/status" | jq '.gpu_info, .total_slices, .allocated_slices'
echo

echo "3. Allocate 2 slices to test-pod-1:"
curl -s -X POST "$API_URL/allocate" \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "test-pod-1", "slices": 2}' | jq '.'
echo

echo "4. Allocate 1 slice to test-pod-2:"
curl -s -X POST "$API_URL/allocate" \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "test-pod-2", "slices": 1}' | jq '.'
echo

echo "5. Check allocation status:"
curl -s "$API_URL/status" | jq '.allocation_table | to_entries[] | select(.value.allocated == true) | {slice: .key, pod: .value.pod_name, memory_gb: .value.memory_limit_gb}'
echo

echo "6. Try to over-allocate (should fail):"
curl -s -X POST "$API_URL/allocate" \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "test-pod-3", "slices": 5}' | jq '.'
echo

echo "7. Release test-pod-1:"
curl -s -X POST "$API_URL/release" \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "test-pod-1"}' | jq '.'
echo

echo "8. Final status:"
curl -s "$API_URL/status" | jq '{allocated_slices: .allocated_slices, active_processes: (.active_processes | length)}'
echo

echo "9. Cleanup - release test-pod-2:"
curl -s -X POST "$API_URL/release" \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "test-pod-2"}' | jq '.'

echo
echo "=== Test Complete ==="