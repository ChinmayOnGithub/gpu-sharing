# GPU Slice Device Plugin Setup Guide

## Prerequisites

1. **Go 1.21+** installed on your system
2. **Docker** for building container images
3. **Kubernetes cluster** with GPU nodes
4. **kubectl** configured to access your cluster

## Step 1: Build and Deploy

```bash
# Make scripts executable
chmod +x build.sh deploy.sh verify.sh

# Build the Go binary locally (optional, for testing)
./build.sh

# Build Docker image and deploy to Kubernetes
./deploy.sh
```

## Step 2: Verify Deployment

```bash
# Run comprehensive verification
./verify.sh
```

## Step 3: Manual Verification Commands

If you prefer to run commands manually:

```bash
# Check if pods are running
kubectl get pods -n kube-system -l app=gpu-slice-device-plugin

# Check logs
kubectl logs -n kube-system -l app=gpu-slice-device-plugin

# Verify GPU slice resources (should show "6" for each GPU node)
kubectl get nodes -o json | jq '.items[].status.allocatable'

# Look specifically for GPU slices
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpu_slices: .status.allocatable."example.com/gpu-slice"}'
```

## Expected Output

You should see:
- Device plugin pods running on GPU nodes
- Logs showing successful registration
- Node allocatable resources showing `"example.com/gpu-slice": "6"`

## Testing with RTX 3060 6GB

Your ASUS A15 with RTX 3060 6GB should work perfectly. The device plugin will:
1. Detect the GPU node
2. Advertise 6 GPU slices
3. Mount `/dev/nvidia0` to containers requesting slices

## Troubleshooting

1. **Pods not starting**: Check node labels with `kubectl get nodes --show-labels`
2. **No GPU resources**: Check device plugin logs for registration errors
3. **Permission issues**: Ensure the DaemonSet runs with privileged security context

## Node Labeling

The deploy script automatically labels all nodes with `accelerator=nvidia`. For production, label only GPU nodes:

```bash
kubectl label node <gpu-node-name> accelerator=nvidia
```