#!/bin/bash

echo "🔍 DEBUGGING K8S API CONNECTION"
echo "==============================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Check k3s API server status:"
sudo systemctl status k3s | head -10

echo -e "\n2. Check k3s API server endpoint:"
$K config view --minify | grep server

echo -e "\n3. Check if API server is listening:"
sudo netstat -tlnp | grep :6443 || echo "API server not listening on 6443"

echo -e "\n4. Check cluster info:"
$K cluster-info

echo -e "\n5. Check scaler pod network:"
POD=$($K get pods -l app=custom-gpu-scaler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ ! -z "$POD" ]; then
    echo "Scaler pod: $POD"
    echo "Pod IP:"
    $K get pod $POD -o jsonpath='{.status.podIP}'
    echo -e "\nPod node:"
    $K get pod $POD -o jsonpath='{.spec.nodeName}'
    echo -e "\nTesting connection from pod:"
    $K exec $POD -- nslookup kubernetes.default.svc.cluster.local || echo "DNS resolution failed"
    $K exec $POD -- wget -qO- --timeout=5 https://kubernetes.default.svc.cluster.local/api/v1 2>&1 || echo "API connection failed"
fi

echo -e "\n6. Check service account token:"
if [ ! -z "$POD" ]; then
    $K exec $POD -- ls -la /var/run/secrets/kubernetes.io/serviceaccount/ || echo "No service account token"
fi