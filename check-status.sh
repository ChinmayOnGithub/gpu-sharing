#!/bin/bash

echo "🔍 FRACTIONAL GPU SYSTEM STATUS CHECK"
echo "====================================="

K="sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl"

echo "1. DaemonSet Status:"
$K get daemonsets -n kube-system | grep gpu-sidecar || echo "❌ No GPU DaemonSet found"

echo -e "\n2. Deployments:"
$K get deployments || echo "❌ No deployments found"

echo -e "\n3. Pods:"
$K get pods -o wide

echo -e "\n4. HPA Status:"
$K get hpa || echo "❌ No HPA found"

echo -e "\n5. GPU Slice Advertisement:"
GPU_SLICES=$($K describe node jade | grep "example.com/gpu-slice" | head -1 | awk '{print $2}' || echo "0")
echo "GPU slices advertised: $GPU_SLICES/6"

echo -e "\n6. GPU Slice Allocation:"
ALLOCATED_SLICES=$($K get pods -o json | jq -r '.items[] | select(.status.phase=="Running") | .spec.containers[] | .resources.requests["example.com/gpu-slice"] // empty' | awk '{sum+=$1} END {print sum+0}')
echo "GPU slices allocated: $ALLOCATED_SLICES/6"
echo "GPU slices available: $((6-ALLOCATED_SLICES))/6"

echo -e "\n7. Port Forward Status:"
if pgrep -f "kubectl.*port-forward.*8003" >/dev/null; then
    echo "✅ HPA port forward (8003) is running"
else
    echo "❌ HPA port forward (8003) not running"
fi

if pgrep -f "kubectl.*port-forward.*8004" >/dev/null; then
    echo "✅ Custom port forward (8004) is running"
else
    echo "❌ Custom port forward (8004) not running"
fi

echo -e "\n8. Application Health:"
if curl -s http://localhost:8003/health >/dev/null 2>&1; then
    echo "✅ HPA app is healthy"
else
    echo "❌ HPA app not accessible"
fi

if curl -s http://localhost:8004/health >/dev/null 2>&1; then
    echo "✅ Custom app is healthy"
else
    echo "❌ Custom app not accessible"
fi

echo -e "\n9. System Summary:"
if [ "$GPU_SLICES" -gt 0 ] && [ "$ALLOCATED_SLICES" -gt 0 ]; then
    echo "✅ Fractional GPU system is working!"
    echo "   - GPU slices advertised: $GPU_SLICES"
    echo "   - GPU slices allocated: $ALLOCATED_SLICES"
    echo "   - System ready for demo"
elif [ "$GPU_SLICES" -gt 0 ]; then
    echo "⚠️  GPU slices advertised but none allocated yet"
    echo "   - This is normal if pods are still starting"
else
    echo "❌ GPU slices not advertised - DaemonSet issue"
fi

echo -e "\n=== Detailed Diagnostics ==="
echo "GPU Sidecar Pod Status:"
$K get pods -n kube-system -l app=gpu-sidecar

echo -e "\nGPU Slice Details:"
$K describe node jade | grep -A 2 -B 2 "example.com/gpu-slice" || echo "No GPU slices found"

POD=$($K get pods -n kube-system -l app=gpu-sidecar -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ ! -z "$POD" ]; then
    echo -e "\nGPU Manager Logs (last 5 lines):"
    $K logs -n kube-system $POD -c gpu-manager --tail=5 2>/dev/null || echo "No logs available"
    
    echo -e "\nDevice Plugin Logs (last 5 lines):"
    $K logs -n kube-system $POD -c gpu-slice-plugin --tail=5 2>/dev/null || echo "No logs available"
fi