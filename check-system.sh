#!/bin/bash

echo "🔍 CHECKING CURRENT SYSTEM STATUS"
echo "================================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Deployments:"
$K get deployments

echo -e "\n2. Pods:"
$K get pods -o wide

echo -e "\n3. Services:"
$K get services

echo -e "\n4. GPU slices:"
$K describe node jade | grep "example.com/gpu-slice" || echo "No GPU slices found"

echo -e "\n5. Port forwards:"
ps aux | grep port-forward | grep -v grep || echo "No port forwards running"

echo -e "\n6. Test connectivity:"
curl -s http://localhost:8003/health 2>/dev/null && echo "✅ HPA app accessible" || echo "❌ HPA app not accessible"
curl -s http://localhost:8004/health 2>/dev/null && echo "✅ Custom app accessible" || echo "❌ Custom app not accessible"