#!/bin/bash
set -e

echo "🔧 APPLYING TARGETED FIXES"
echo "=========================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Fix kubeconfig permissions..."
sudo chmod 644 /etc/rancher/k3s/k3s.yaml

echo "2. Apply ClusterRole RBAC for scaler..."
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

echo "3. Rebuild scaler with fixed config..."
docker build --no-cache -t custom-gpu-scaler:latest k8s/custom-scaler-image/
docker save custom-gpu-scaler:latest | sudo k3s ctr images import -

echo "4. Restart scaler deployment..."
$K rollout restart deployment/custom-gpu-scaler
$K rollout status deployment/custom-gpu-scaler --timeout=60s

echo "5. Fix port forwards..."
pkill -f "port-forward" 2>/dev/null || true
sleep 2

nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/hpa-fractional-app 8003:8080 >/tmp/pf-hpa-fixed.log 2>&1 &
HPA_PID=$!
sleep 3

nohup kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml port-forward service/custom-fractional-app 8004:8080 >/tmp/pf-custom-fixed.log 2>&1 &
CUSTOM_PID=$!
sleep 3

echo "6. Test connectivity..."
curl -s http://localhost:8003/health >/dev/null && echo "✅ HPA app accessible" || echo "❌ HPA app not accessible"
curl -s http://localhost:8004/health >/dev/null && echo "✅ Custom app accessible" || echo "❌ Custom app not accessible"

echo "7. Check scaler logs..."
$K logs deployment/custom-gpu-scaler --tail=10

echo -e "\n✅ FIXES APPLIED!"
echo "Port forwards: kill $HPA_PID $CUSTOM_PID"
echo "Now run: python3 demo-fractional-clean.py"