#!/bin/bash
OUT=${1:-experiment_results.csv}
echo "timestamp,gpu_util_percent,gpu_mem_used_mb,active_pods" > $OUT
for i in $(seq 1 90); do
  ts=$(date +%s)
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d '\n' | sed 's/,/;/g')
  mem=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d '\n' | sed 's/,/;/g')
  active=$(sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get pods --no-headers | egrep 'gpu-test-pod|gpu-pod' | wc -l)
  echo "${ts},${util},${mem},${active}" >> $OUT
  sleep 1
done
echo "Saved metrics to $OUT"
