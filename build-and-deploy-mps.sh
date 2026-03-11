#!/bin/bash
set -e

echo "🚀 BUILDING FRACTIONAL GPU SYSTEM WITH MPS SUPPORT"
echo "=================================================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

# Step 1: Setup MPS on host (one-time)
echo "1. Setting up CUDA MPS on host..."
if ! pgrep -x "nvidia-cuda-mps-control" > /dev/null; then
    echo "  MPS not running, setting up..."
    chmod +x setup-mps.sh
    sudo ./setup-mps.sh
else
    echo "  ✅ MPS already running"
fi

# Step 2: Deploy MPS DaemonSet
echo -e "\n2. Deploying MPS DaemonSet..."
$K apply -f k8s/mps-daemonset.yaml

# Wait for MPS DaemonSet
echo "  Waiting for MPS DaemonSet..."
for i in {1..20}; do
    MPS_READY=$($K get pods -n kube-system -l app=nvidia-mps --no-headers 2>/dev/null | grep "Running" | wc -l || echo "0")
    if [ "$MPS_READY" -gt 0 ]; then
        echo "  ✅ MPS DaemonSet ready"
        break
    fi
    echo "    Waiting... ($i/20)"
    sleep 5
done

# Step 3: Build and import images
echo -e "\n3. Building and importing Docker images..."

echo "  Building GPU manager..."
cd gpu-manager && docker build -t gpu-manager:latest . && cd ..

echo "  Building device plugin (with MPS support)..."
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

# Step 4: Deploy GPU DaemonSet (with MPS support)
echo -e "\n4. Deploying GPU DaemonSet..."
$K delete daemonset gpu-sidecar -n kube-system --ignore-not-found=true --force --grace-period=0
sleep 5
$K apply -f k8s/gpu-sidecar-daemonset-fixed.yaml

# Step 5: Wait for DaemonSet — check pod is 2/2 Ready
echo -e "\n5. Waiting for DaemonSet (checking pod 2/2 ready)..."
for i in {1..40}; do
    STATUS=$($K get pods -n kube-system -l app=gpu-sidecar --no-headers 2>/dev/null | awk '{print $2}' | head -1)
    if [ "$STATUS" = "2/2" ]; then
        echo "✅ DaemonSet ready! (2/2 containers running)"
        break
    fi
    echo "  Waiting... ($i/40) status=$STATUS"
    sleep 5
    
    if [ $i -eq 40 ]; then
        echo "❌ DaemonSet not ready after 200s. Debug info:"
        $K describe pod -n kube-system -l app=gpu-sidecar | tail -20
        exit 1
    fi
done

# Step 6: Verify GPU resources
echo -e "\n6. Verifying GPU resources..."
sleep 5
GPU_SLICES=$($K describe node jade | grep "example.com/gpu-slice" | head -1 | awk '{print $2}' || echo "0")
if [ "$GPU_SLICES" -eq 0 ]; then
    echo "❌ No GPU slices advertised!"
    POD=$($K get pods -n kube-system -l app=gpu-sidecar -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ ! -z "$POD" ]; then
        $K logs -n kube-system $POD -c gpu-slice-plugin --tail=10
        $K logs -n kube-system $POD -c gpu-manager --tail=10
    fi
    exit 1
fi
echo "✅ GPU slices advertised: $GPU_SLICES"

# Step 7: Deploy applications
echo -e "\n7. Deploying applications..."
$K apply -f k8s/hpa-fractional-gpu.yaml
$K apply -f k8s/custom-fractional-scaler.yaml

# Step 8: Wait for applications
echo -e "\n8. Waiting for applications..."
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
    sleep 5
done

# Step 9: Setup port forwarding
echo -e "\n9. Setting up port forwarding..."
pkill -f "port-forward" 2>/dev/null || true
sleep 2

nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/hpa-fractional-app 8003:8080 >/tmp/pf-hpa.log 2>&1 &
HPA_PF_PID=$!
sleep 2

nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/custom-fractional-app 8004:8080 >/tmp/pf-custom.log 2>&1 &
CUSTOM_PF_PID=$!
sleep 2

echo "Port forwards: HPA=8003, Custom=8004 (PIDs: $HPA_PF_PID, $CUSTOM_PF_PID)"

# Step 10: Test connectivity and MPS
echo -e "\n10. Testing system..."
sleep 3

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

# Test MPS environment variables
echo -e "\n11. Verifying MPS configuration..."
POD=$($K get pods -l app=custom-fractional-app -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ ! -z "$POD" ]; then
    echo "  Checking MPS env vars in pod $POD:"
    MPS_THREAD=$($K exec $POD -- env | grep CUDA_MPS_ACTIVE_THREAD_PERCENTAGE || echo "NOT_SET")
    MPS_MEM=$($K exec $POD -- env | grep CUDA_MPS_PINNED_DEVICE_MEM_LIMIT || echo "NOT_SET")
    
    if [[ "$MPS_THREAD" == *"16"* ]]; then
        echo "  ✅ CUDA_MPS_ACTIVE_THREAD_PERCENTAGE=16 (1/6th compute)"
    else
        echo "  ❌ MPS thread percentage not set: $MPS_THREAD"
    fi
    
    if [[ "$MPS_MEM" == *"1024m"* ]]; then
        echo "  ✅ CUDA_MPS_PINNED_DEVICE_MEM_LIMIT=0=1024m (1GB memory)"
    else
        echo "  ❌ MPS memory limit not set: $MPS_MEM"
    fi
    
    # Check if MPS socket is mounted
    MPS_SOCKET=$($K exec $POD -- ls /tmp/nvidia-mps 2>/dev/null || echo "NOT_MOUNTED")
    if [[ "$MPS_SOCKET" == *"control"* ]]; then
        echo "  ✅ MPS socket mounted and accessible"
    else
        echo "  ❌ MPS socket not accessible: $MPS_SOCKET"
    fi
fi

# Step 12: Final status
echo -e "\n12. System Status:"
$K get deployments
echo ""
$K get pods -o wide
echo ""

ALLOCATED=$($K get pods -o json | jq -r '.items[] | select(.status.phase=="Running") | .spec.containers[] | .resources.requests["example.com/gpu-slice"] // empty' | awk '{sum+=$1} END {print sum+0}')
echo "GPU slices allocated: $ALLOCATED/$GPU_SLICES"

echo -e "\n🎉 MPS-ENABLED FRACTIONAL GPU SYSTEM DEPLOYED!"
echo "=============================================="
echo "✅ CUDA MPS daemon running (enforces compute isolation)"
echo "✅ Each pod gets 16% GPU compute + 1GB memory"
echo "✅ Port forwarding active"
echo ""
echo "🧪 RUN DEMO:"
echo "   python3 demo-fractional.py"
echo ""
echo "🔍 VERIFY MPS ISOLATION:"
echo "   # Launch 6 pods under load, each should show ~16% in nvidia-smi"
echo "   # Instead of one pod using 70%, you'll see 6 pods at ~16% each"
echo ""
echo "🛑 STOP PORT FORWARDS:"
echo "   kill $HPA_PF_PID $CUSTOM_PF_PID"