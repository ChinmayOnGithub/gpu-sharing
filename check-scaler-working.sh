#!/bin/bash

echo "🔍 CHECKING IF SCALER IS WORKING"
echo "================================"

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "1. Scaler pod status:"
$K get pods -l app=custom-gpu-scaler -o wide

echo -e "\n2. Scaler deployment status:"
$K get deployment custom-gpu-scaler

echo -e "\n3. Scaler logs (last 20 lines):"
$K logs deployment/custom-gpu-scaler --tail=20

echo -e "\n4. Check if scaler is actually making scaling decisions:"
echo "Looking for scaling logs..."
$K logs deployment/custom-gpu-scaler --tail=50 | grep -E "SCALE|Current:|Metrics:" || echo "❌ No scaling logs found"

echo -e "\n5. Check target app metrics:"
echo "Custom app metrics:"
curl -s http://localhost:8004/metrics | head -10 || echo "❌ Can't get metrics"

echo -e "\n6. Check if scaler can reach the app:"
SCALER_POD=$($K get pods -l app=custom-gpu-scaler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ ! -z "$SCALER_POD" ]; then
    echo "Testing from scaler pod:"
    $K exec $SCALER_POD -- curl -s http://custom-fractional-app:8080/metrics --max-time 5 | head -5 || echo "❌ Scaler can't reach app"
fi

echo -e "\n7. Check scaler environment variables:"
if [ ! -z "$SCALER_POD" ]; then
    echo "Scaler env vars:"
    $K exec $SCALER_POD -- env | grep -E "KUBERNETES|NAMESPACE|DEPLOYMENT|APP_LABEL" || echo "No relevant env vars"
fi

echo -e "\n8. Manual scaling test:"
echo "Current replicas:"
$K get deployment custom-fractional-app -o jsonpath='{.status.readyReplicas}'
echo ""
echo "Manually scaling to 2 to test if it works:"
$K scale deployment custom-fractional-app --replicas=2
sleep 10
echo "New replicas:"
$K get deployment custom-fractional-app -o jsonpath='{.status.readyReplicas}'
echo ""
echo "Scaling back to 1:"
$K scale deployment custom-fractional-app --replicas=1

echo -e "\n🔍 DIAGNOSIS:"
echo "============="
echo "If you see:"
echo "❌ No scaling logs → Scaler not running or crashed"
echo "❌ Can't reach app → Network/service issue"
echo "❌ Wrong env vars → Configuration issue"
echo "✅ Scaling logs but no action → Thresholds still too high"