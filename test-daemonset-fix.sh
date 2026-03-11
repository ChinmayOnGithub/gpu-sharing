#!/bin/bash
set -e

echo "🔧 TESTING DAEMONSET FIX"
echo "========================"

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Checking current DaemonSet status..."
$K get pods -n kube-system -l app=gpu-sidecar

echo -e "\n2. Waiting for 2/2 ready status..."
for i in {1..20}; do
    STATUS=$($K get pods -n kube-system -l app=gpu-sidecar --no-headers 2>/dev/null | awk '{print $2}' | head -1)
    if [ "$STATUS" = "2/2" ]; then
        echo "✅ DaemonSet ready! (2/2 containers running)"
        break
    fi
    echo "  Waiting... ($i/20) status=$STATUS"
    sleep 5
    
    if [ $i -eq 20 ]; then
        echo "❌ DaemonSet not ready. Checking details..."
        $K describe pod -n kube-system -l app=gpu-sidecar | grep -A5 "Containers:"
        $K describe pod -n kube-system -l app=gpu-sidecar | grep "Ready:"
        exit 1
    fi
done

echo -e "\n3. Verifying GPU slices are advertised..."
sleep 5
GPU_SLICES=$($K describe node jade | grep "example.com/gpu-slice" | head -1 | awk '{print $2}' || echo "0")
echo "GPU slices advertised: $GPU_SLICES"

if [ "$GPU_SLICES" -gt 0 ]; then
    echo "✅ DaemonSet fix successful! Ready for deployment."
else
    echo "❌ GPU slices not advertised yet. Check logs:"
    POD=$($K get pods -n kube-system -l app=gpu-sidecar -o jsonpath='{.items[0].metadata.name}')
    $K logs -n kube-system $POD -c gpu-slice-plugin --tail=5
    $K logs -n kube-system $POD -c gpu-manager --tail=5
fi