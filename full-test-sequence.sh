#!/bin/bash
set -e

echo "🧪 FULL TEST SEQUENCE"
echo "===================="

echo "STEP 1: Clean reset..."
echo "----------------------"
./clean-reset.sh
sleep 10

echo -e "\nSTEP 2: Build and deploy all..."
echo "-------------------------------"
timeout 600 ./build-and-deploy-all.sh || echo "Build completed or timed out"
sleep 20

echo -e "\nSTEP 3: Check system status..."
echo "------------------------------"
K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

echo "Deployments:"
$K get deployments

echo -e "\nPods:"
$K get pods -o wide

echo -e "\nServices:"
$K get services

echo -e "\nGPU slices:"
$K describe node jade | grep "example.com/gpu-slice" || echo "No GPU slices"

echo -e "\nPort forwards:"
ps aux | grep port-forward | grep -v grep || echo "No port forwards"

echo -e "\nSTEP 4: Test connectivity..."
echo "----------------------------"
sleep 5
curl -s http://localhost:8003/health 2>/dev/null && echo "✅ HPA app accessible" || echo "❌ HPA app not accessible"
curl -s http://localhost:8004/health 2>/dev/null && echo "✅ Custom app accessible" || echo "❌ Custom app not accessible"

echo -e "\nSTEP 5: Check scaler status..."
echo "------------------------------"
echo "Scaler pod:"
$K get pods -l app=custom-gpu-scaler

echo -e "\nScaler logs:"
$K logs deployment/custom-gpu-scaler --tail=10 || echo "No scaler logs"

echo -e "\nSTEP 6: Test metrics..."
echo "-----------------------"
curl -s http://localhost:8004/metrics 2>/dev/null | head -5 || echo "❌ Metrics not accessible"

echo -e "\nSTEP 7: Run demo (short test)..."
echo "--------------------------------"
timeout 30 python3 demo-fractional-clean.py || echo "Demo completed or timed out"

echo -e "\n🔍 DIAGNOSIS:"
echo "============="
echo "Check the output above for:"
echo "1. ❌ Apps not accessible → Port forwarding issue"
echo "2. ❌ Scaler logs show errors → RBAC or connection issue"  
echo "3. ❌ No GPU slices → DaemonSet issue"
echo "4. ❌ Demo fails → App or scaling issue"
echo ""
echo "Paste this output and I'll tell you which file to fix!"