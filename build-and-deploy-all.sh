#!/bin/bash
set -e

echo "🚀 BUILDING AND DEPLOYING FRACTIONAL GPU SYSTEM"
echo "==============================================="

K="sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl"

# Step 1: Build and import images
echo "1. Building and importing Docker images..."

echo "  Building GPU manager..."
cd gpu-manager && docker build -t gpu-manager:latest . && cd ..

echo "  Building device plugin..."
cd device-plugin && docker build -t gpu-slice-plugin:latest . && cd ..

echo "  Building GPU app..."
cd k8s/gpu-app-image && docker build -t gpu-fractional-app:latest . && cd ../..

echo "  Building custom scaler..."
cd k8s/custom-scaler-image && docker build -t custom-gpu-scaler:latest . && cd ../..

echo "  Importing to k3s..."
docker save gpu-manager:latest | sudo k3s ctr images import -
docker save gpu-slice-plugin:latest | sudo k3s ctr images import -
docker save gpu-fractional-app:latest | sudo k3s ctr images import -
docker save custom-gpu-scaler:latest | sudo k3s ctr images import -

echo "✅ All images built and imported"

# Step 2: Deploy DaemonSet
echo -e "\n2. Deploying GPU DaemonSet..."
$K delete daemonset gpu-sidecar -n kube-system --ignore-not-found=true --force --grace-period=0
sleep 10
$K apply -f k8s/gpu-sidecar-daemonset-fixed.yaml

# Step 3: Wait for DaemonSet
echo -e "\n3. Waiting for DaemonSet..."
for i in {1..30}; do
    READY=$($K get daemonset gpu-sidecar -n kube-system -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
    if [ "$READY" -gt 0 ]; then
        echo "✅ DaemonSet ready!"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 10
done

# Step 4: Verify GPU resources
echo -e "\n4. Verifying GPU resources..."
GPU_SLICES=$($K describe node jade | grep "example.com/gpu-slice" | head -1 | awk '{print $2}' || echo "0")
if [ "$GPU_SLICES" -eq 0 ]; then
    echo "❌ No GPU slices advertised!"
    echo "DaemonSet logs:"
    POD=$($K get pods -n kube-system -l app=gpu-sidecar -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ ! -z "$POD" ]; then
        $K logs -n kube-system $POD -c gpu-slice-plugin --tail=5
        $K logs -n kube-system $POD -c gpu-manager --tail=5
    fi
    exit 1
fi
echo "✅ GPU slices advertised: $GPU_SLICES"

# Step 5: Deploy HPA application
echo -e "\n5. Deploying HPA application..."
$K apply -f k8s/hpa-fractional-gpu.yaml

# Step 6: Deploy Custom Scaler
echo -e "\n6. Deploying Custom Scaler..."
$K apply -f k8s/custom-fractional-scaler.yaml

# Step 7: Wait for applications
echo -e "\n7. Waiting for applications..."
for i in {1..30}; do
    HPA_READY=$($K get deployment hpa-fractional-app -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    CUSTOM_READY=$($K get deployment custom-fractional-app -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    SCALER_READY=$($K get deployment custom-gpu-scaler -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    
    if [ "$HPA_READY" -gt 0 ] && [ "$CUSTOM_READY" -gt 0 ] && [ "$SCALER_READY" -gt 0 ]; then
        echo "✅ All applications ready!"
        echo "  HPA: $HPA_READY pods"
        echo "  Custom: $CUSTOM_READY pods" 
        echo "  Scaler: $SCALER_READY pods"
        break
    fi
    
    echo "  Waiting... ($i/30) HPA:$HPA_READY Custom:$CUSTOM_READY Scaler:$SCALER_READY"
    sleep 10
    
    if [ $i -eq 30 ]; then
        echo "⚠️  Some applications not ready. Current status:"
        $K get pods -o wide
        echo ""
        echo "Check pod issues:"
        $K get events --sort-by='.lastTimestamp' | tail -10
    fi
done

# Step 8: Setup port forwarding
echo -e "\n8. Setting up port forwarding..."
pkill -f "kubectl.*port-forward" || true
sleep 2

$K port-forward service/hpa-fractional-app 8003:8080 >/dev/null 2>&1 &
HPA_PF_PID=$!
sleep 2

$K port-forward service/custom-fractional-app 8004:8080 >/dev/null 2>&1 &
CUSTOM_PF_PID=$!
sleep 2

echo "Port forwards: HPA=8003, Custom=8004 (PIDs: $HPA_PF_PID, $CUSTOM_PF_PID)"

# Step 9: Test connectivity
echo -e "\n9. Testing connectivity..."
sleep 5
if curl -s http://localhost:8003/health >/dev/null; then
    echo "✅ HPA app accessible"
else
    echo "❌ HPA app not accessible"
fi

if curl -s http://localhost:8004/health >/dev/null; then
    echo "✅ Custom app accessible"
else
    echo "❌ Custom app not accessible"
fi

# Step 10: Final status
echo -e "\n10. System Status:"
echo "Deployments:"
$K get deployments

echo -e "\nPods:"
$K get pods -o wide

echo -e "\nHPA:"
$K get hpa

echo -e "\nGPU Usage:"
ALLOCATED=$($K get pods -o json | jq -r '.items[] | select(.status.phase=="Running") | .spec.containers[] | .resources.requests["example.com/gpu-slice"] // empty' | awk '{sum+=$1} END {print sum+0}')
echo "GPU slices allocated: $ALLOCATED/$GPU_SLICES"

echo -e "\n🎉 DEPLOYMENT COMPLETE!"
echo "================================"
echo "✅ Fractional GPU system deployed"
echo "✅ Port forwarding active"
echo ""
echo "🧪 RUN DEMO:"
echo "   python3 demo-fractional.py"
echo ""
echo "🛑 STOP PORT FORWARDS:"
echo "   kill $HPA_PF_PID $CUSTOM_PF_PID"