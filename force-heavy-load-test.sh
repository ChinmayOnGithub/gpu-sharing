#!/bin/bash

echo "🔥 FORCE HEAVY LOAD TEST"
echo "======================="

echo "This will generate HEAVY load to force scaling"
echo "Press Ctrl+C to stop"
echo ""

# Generate heavy load with larger matrix operations
echo "Starting 20 heavy workers..."
for i in {1..20}; do
    (
        while true; do
            curl -s "http://localhost:8004/gpu-work?type=matmul&size=1500" >/dev/null &
            sleep 0.05  # Very fast requests
        done
    ) &
done

echo "Load started. Monitoring scaling..."

K="sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"

# Monitor for 2 minutes
for i in {1..24}; do
    REPLICAS=$($K get deployment custom-fractional-app -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    GPU_USAGE=$($K get pods -o json 2>/dev/null | python3 -c "
import json,sys
try:
    data=json.load(sys.stdin)
    total=sum(int(c.get('resources',{}).get('requests',{}).get('example.com/gpu-slice',0))
    for p in data.get('items',[]) if p.get('status',{}).get('phase')=='Running'
    for c in p.get('spec',{}).get('containers',[]))
    print(total)
except:
    print(0)
" 2>/dev/null || echo "0")
    
    # Get app metrics
    METRICS=$(curl -s http://localhost:8004/metrics 2>/dev/null || echo "{}")
    
    echo "[$i/24] Replicas: $REPLICAS | GPU: $GPU_USAGE/6 | $(echo $METRICS | grep -o '"gpu_utilization":[0-9.]*' | cut -d: -f2)% GPU | $(echo $METRICS | grep -o '"concurrent_requests":[0-9]*' | cut -d: -f2) concurrent"
    
    sleep 5
done

echo ""
echo "Stopping load..."
pkill -f "curl.*gpu-work" 2>/dev/null || true

echo "Final status:"
$K get deployment custom-fractional-app
$K logs deployment/custom-gpu-scaler --tail=10