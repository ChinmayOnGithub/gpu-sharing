#!/bin/bash

echo "🔍 CHECKING SCALER STATUS"
echo "========================"

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Scaler pod status:"
$K get pods -l app=custom-gpu-scaler -o wide

echo -e "\n2. Scaler deployment status:"
$K get deployment custom-gpu-scaler

echo -e "\n3. Recent scaler logs:"
$K logs deployment/custom-gpu-scaler --tail=20

echo -e "\n4. Service account check:"
$K get serviceaccount custom-gpu-scaler

echo -e "\n5. RBAC permissions:"
$K get clusterrole custom-gpu-scaler
$K get clusterrolebinding custom-gpu-scaler

echo -e "\n6. Target app status:"
$K get deployment custom-fractional-app
$K get pods -l app=custom-fractional-app

echo -e "\n7. GPU slice usage:"
$K describe node jade | grep "example.com/gpu-slice" || echo "No GPU slices found"

echo -e "\n8. Test app connectivity:"
curl -s http://localhost:8004/health 2>/dev/null && echo "✅ Custom app accessible" || echo "❌ Custom app not accessible"

echo -e "\n9. App metrics:"
curl -s http://localhost:8004/metrics 2>/dev/null | head -10 || echo "❌ Metrics not accessible"