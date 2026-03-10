#!/bin/bash

set -e

echo "Building GPU Slice Device Plugin Docker image..."
docker build -t gpu-slice-plugin:latest .

echo "Labeling GPU nodes..."
# Label nodes with NVIDIA GPUs (adjust node names as needed)
kubectl label nodes --all accelerator=nvidia --overwrite

echo "Deploying DaemonSet..."
kubectl apply -f daemonset.yaml

echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=gpu-slice-device-plugin -n kube-system --timeout=60s

echo "Checking pod status..."
kubectl get pods -n kube-system -l app=gpu-slice-device-plugin

echo "Checking logs..."
kubectl logs -n kube-system -l app=gpu-slice-device-plugin --tail=20

echo "Verifying GPU slice resources on nodes..."
kubectl get nodes -o json | jq '.items[].status.allocatable | select(."example.com/gpu-slice")'

echo "Full node allocatable resources:"
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, allocatable: .status.allocatable}'