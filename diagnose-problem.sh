#!/bin/bash

echo "🔍 PROBLEM DIAGNOSIS"
echo "==================="

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. SYSTEM STATUS:"
echo "----------------"
echo "Deployments:"
$K get deployments 2>/dev/null || echo "❌ kubectl not working"

echo -e "\nPods:"
$K get pods 2>/dev/null || echo "❌ kubectl not working"

echo -e "\n2. SCALER DIAGNOSIS:"
echo "-------------------"
SCALER_POD=$($K get pods -l app=custom-gpu-scaler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -z "$SCALER_POD" ]; then
    echo "❌ PROBLEM: No scaler pod found"
    echo "📁 FIX FILE: k8s/custom-fractional-scaler.yaml"
else
    echo "✅ Scaler pod exists: $SCALER_POD"
    echo "Scaler status:"
    $K get pod $SCALER_POD
    echo -e "\nScaler logs:"
    $K logs $SCALER_POD --tail=5
    
    if $K logs $SCALER_POD --tail=20 | grep -q "No route to host"; then
        echo "❌ PROBLEM: Scaler can't connect to Kubernetes API"
        echo "📁 FIX FILE: fix-scaler-rbac-simple.yaml (apply this)"
    elif $K logs $SCALER_POD --tail=20 | grep -q "tenacity"; then
        echo "❌ PROBLEM: Missing tenacity dependency"
        echo "📁 FIX FILE: k8s/custom-scaler-image/Dockerfile"
    elif $K logs $SCALER_POD --tail=20 | grep -q "No pods found"; then
        echo "❌ PROBLEM: Scaler can't find target app"
        echo "📁 FIX FILE: k8s/custom-scaler-image/gpu_scaler.py (wrong labels)"
    else
        echo "✅ Scaler seems to be working"
    fi
fi

echo -e "\n3. APP DIAGNOSIS:"
echo "----------------"
APP_POD=$($K get pods -l app=custom-fractional-app -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -z "$APP_POD" ]; then
    echo "❌ PROBLEM: No app pod found"
    echo "📁 FIX FILE: k8s/custom-fractional-scaler.yaml"
else
    echo "✅ App pod exists: $APP_POD"
    echo "App status:"
    $K get pod $APP_POD
fi

echo -e "\n4. CONNECTIVITY DIAGNOSIS:"
echo "-------------------------"
if curl -s http://localhost:8004/health >/dev/null 2>&1; then
    echo "✅ App accessible via port forward"
else
    echo "❌ PROBLEM: App not accessible"
    if ps aux | grep -q "port-forward.*8004"; then
        echo "✅ Port forward running"
        echo "📁 FIX FILE: k8s/custom-fractional-scaler.yaml (app not responding)"
    else
        echo "❌ Port forward not running"
        echo "📁 FIX FILE: build-and-deploy-all.sh (port forward setup)"
    fi
fi

echo -e "\n5. GPU SLICES DIAGNOSIS:"
echo "-----------------------"
GPU_SLICES=$($K describe node jade 2>/dev/null | grep "example.com/gpu-slice" | head -1 | awk '{print $2}' || echo "0")
if [ "$GPU_SLICES" -eq 0 ]; then
    echo "❌ PROBLEM: No GPU slices advertised"
    echo "📁 FIX FILE: k8s/gpu-sidecar-daemonset-fixed.yaml or device-plugin/server.go"
else
    echo "✅ GPU slices available: $GPU_SLICES"
fi

echo -e "\n📋 SUMMARY:"
echo "==========="
echo "Run this diagnosis and I'll tell you exactly which file to fix!"