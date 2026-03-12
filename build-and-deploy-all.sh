#!/bin/bash
set -e

echo "🚀 BUILDING AND DEPLOYING FRACTIONAL GPU SYSTEM"
echo "==============================================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

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

# Step 2: Setup prerequisites
echo -e "\n2. Setting up prerequisites..."

# Check if NVIDIA GPU is present
if ! lspci | grep -i nvidia >/dev/null 2>&1; then
    echo "❌ No NVIDIA GPU detected. This system requires an NVIDIA GPU."
    exit 1
fi
echo "✅ NVIDIA GPU detected"

# Install NVIDIA Container Toolkit if not present
if ! which nvidia-container-runtime >/dev/null 2>&1; then
    echo "  Installing NVIDIA Container Toolkit..."
    distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
    
    # Configure Docker to use NVIDIA runtime
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    
    # Configure k3s to use NVIDIA runtime
    sudo mkdir -p /var/lib/rancher/k3s/agent/etc/containerd/
    sudo nvidia-ctk runtime configure --runtime=containerd --config=/var/lib/rancher/k3s/agent/etc/containerd/config.toml
    sudo systemctl restart k3s
    
    echo "✅ NVIDIA Container Toolkit installed and configured"
    echo "⚠️  Please wait 30 seconds for k3s to restart..."
    sleep 30
else
    echo "✅ NVIDIA Container Toolkit already installed"
fi

# Install jq if not present (needed for JSON parsing)
if ! which jq >/dev/null 2>&1; then
    echo "  Installing jq for JSON parsing..."
    sudo apt-get update -qq
    sudo apt-get install -y jq
    echo "✅ jq installed"
else
    echo "✅ jq already installed"
fi

# Create required directories
echo "  Creating required directories..."
sudo mkdir -p /var/lib/kubelet/device-plugins
sudo chmod 755 /var/lib/kubelet/device-plugins
echo "✅ Device plugin directory created"

# Label nodes for GPU scheduling
echo "  Labeling nodes for GPU scheduling..."
$K label nodes --all nvidia.com/gpu.present=true --overwrite
$K label nodes --all accelerator=nvidia --overwrite
echo "✅ Nodes labeled for GPU scheduling"

# Step 3: Deploy DaemonSet
echo -e "\n3. Deploying GPU DaemonSet..."
$K delete daemonset gpu-sidecar -n kube-system --ignore-not-found=true --force --grace-period=0
sleep 5
$K apply -f k8s/gpu-sidecar-daemonset-fixed.yaml

# Step 4: Wait for DaemonSet — check pod is 2/2 Ready
echo -e "\n4. Waiting for DaemonSet (checking pod 2/2 ready)..."
for i in {1..40}; do
    STATUS=$($K get pods -n kube-system -l app=gpu-sidecar --no-headers 2>/dev/null | awk '{print $2}' | head -1)
    if [ "$STATUS" = "2/2" ]; then
        echo "✅ DaemonSet ready! (2/2 containers running)"
        break
    fi
    # Show what's happening so we know it's not stuck
    echo "  Waiting... ($i/40) status=$STATUS"
    sleep 5
    
    if [ $i -eq 40 ]; then
        echo "❌ DaemonSet not ready after 200s. Debug info:"
        $K describe pod -n kube-system -l app=gpu-sidecar | tail -20
        exit 1
    fi
done

# Step 5: Verify GPU resources
echo -e "\n5. Verifying GPU resources..."
# Give device plugin 5s to register after becoming ready
sleep 5
NODE_NAME=$($K get nodes -o jsonpath='{.items[0].metadata.name}')
GPU_SLICES=$($K describe node $NODE_NAME | grep "example.com/gpu-slice" | head -1 | awk '{print $2}' || echo "0")
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

# Step 6: Deploy HPA application
echo -e "\n6. Deploying HPA application..."
$K delete deployment hpa-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete service hpa-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete hpa hpa-fractional-autoscaler --ignore-not-found=true --force --grace-period=0
sleep 3
$K apply -f k8s/hpa-fractional-gpu.yaml

# Step 7: Deploy Custom Scaler
echo -e "\n7. Deploying Custom Scaler..."
$K delete deployment custom-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete service custom-fractional-app --ignore-not-found=true --force --grace-period=0
$K delete deployment custom-gpu-scaler --ignore-not-found=true --force --grace-period=0
sleep 3
$K apply -f k8s/custom-fractional-scaler.yaml

# Step 7b: Apply ClusterRole RBAC for scaler API access
echo -e "\n7b. Applying ClusterRole RBAC for scaler..."
$K apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: custom-gpu-scaler
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "deployments/scale", "deployments/status"]
  verbs: ["get", "list", "watch", "patch", "update"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: custom-gpu-scaler
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: custom-gpu-scaler
subjects:
- kind: ServiceAccount
  name: custom-gpu-scaler
  namespace: default
EOF

# Step 8: Wait for applications
echo -e "\n8. Waiting for applications..."
for i in {1..30}; do
    HPA_READY=$($K get deployment hpa-fractional-app -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    CUSTOM_READY=$($K get deployment custom-fractional-app -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    SCALER_READY=$($K get deployment custom-gpu-scaler -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    
    # Handle empty values by defaulting to 0
    HPA_READY=${HPA_READY:-0}
    CUSTOM_READY=${CUSTOM_READY:-0}
    SCALER_READY=${SCALER_READY:-0}
    
    if [ "$HPA_READY" -gt 0 ] && [ "$CUSTOM_READY" -gt 0 ] && [ "$SCALER_READY" -gt 0 ]; then
        echo "✅ All applications ready!"
        echo "  HPA: $HPA_READY pods"
        echo "  Custom: $CUSTOM_READY pods" 
        echo "  Scaler: $SCALER_READY pods"
        break
    fi
    
    echo "  Waiting... ($i/30) HPA:$HPA_READY Custom:$CUSTOM_READY Scaler:$SCALER_READY"
    sleep 5
    
    if [ $i -eq 30 ]; then
        echo "⚠️  Some applications not ready. Current status:"
        $K get pods -o wide
        $K get events --sort-by='.lastTimestamp' | tail -10
    fi
done

# Step 9: Setup port forwarding (without sudo so no password prompt)
echo -e "\n9. Setting up port forwarding..."
pkill -f "port-forward" 2>/dev/null || true
sleep 2

# Fix kubeconfig permissions first
sudo chmod 644 /etc/rancher/k3s/k3s.yaml 2>/dev/null || true

# Use nohup + kubeconfig flag directly (no sudo needed for port-forward)
nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/hpa-fractional-app 8003:8080 >/tmp/pf-hpa.log 2>&1 &
HPA_PF_PID=$!
sleep 3

nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/custom-fractional-app 8004:8080 >/tmp/pf-custom.log 2>&1 &
CUSTOM_PF_PID=$!
sleep 3

echo "Port forwards: HPA=8003, Custom=8004 (PIDs: $HPA_PF_PID, $CUSTOM_PF_PID)"

# Step 10: Test connectivity
echo -e "\n10. Testing connectivity..."
sleep 5

# Test with retries
for attempt in 1 2 3; do
    HPA_OK=false
    CUSTOM_OK=false
    
    if curl -s --max-time 3 http://localhost:8003/health >/dev/null 2>&1; then
        HPA_OK=true
    fi
    
    if curl -s --max-time 3 http://localhost:8004/health >/dev/null 2>&1; then
        CUSTOM_OK=true
    fi
    
    if $HPA_OK && $CUSTOM_OK; then
        echo "✅ HPA app accessible"
        echo "✅ Custom app accessible"
        break
    fi
    
    if [ $attempt -lt 3 ]; then
        echo "  Attempt $attempt/3 failed, retrying..."
        sleep 5
    else
        if ! $HPA_OK; then
            echo "❌ HPA app not accessible — check /tmp/pf-hpa.log"
            echo "  Log: $(tail -3 /tmp/pf-hpa.log 2>/dev/null || echo 'no log')"
        fi
        if ! $CUSTOM_OK; then
            echo "❌ Custom app not accessible — check /tmp/pf-custom.log"
            echo "  Log: $(tail -3 /tmp/pf-custom.log 2>/dev/null || echo 'no log')"
        fi
    fi
done

# Step 11: Final status
echo -e "\n11. System Status:"
$K get deployments

echo ""
$K get pods -o wide

echo ""
$K get hpa

echo ""
# Count GPU slices allocated (with fallback if jq not available)
if which jq >/dev/null 2>&1; then
    ALLOCATED=$($K get pods -o json | jq -r '.items[] | select(.status.phase=="Running") | .spec.containers[] | .resources.requests["example.com/gpu-slice"] // empty' | awk '{sum+=$1} END {print sum+0}')
else
    # Fallback: count running pods that request GPU slices
    ALLOCATED=$($K get pods --field-selector=status.phase=Running -o jsonpath='{range .items[*]}{.spec.containers[*].resources.requests.example\.com/gpu-slice}{"\n"}{end}' 2>/dev/null | grep -v '^$' | awk '{sum+=$1} END {print sum+0}')
fi
echo "GPU slices allocated: $ALLOCATED/$GPU_SLICES"

echo -e "\n🎉 DEPLOYMENT COMPLETE!"
echo "================================"
echo "✅ Fractional GPU system deployed"
echo "✅ Port forwarding active (no sudo needed)"
echo ""
echo "🧪 RUN DEMO:"
echo "   python3 demo-fractional.py"
echo ""
echo "🛑 STOP PORT FORWARDS:"
echo "   kill $HPA_PF_PID $CUSTOM_PF_PID"