# GPU Slice Allocation System

A Kubernetes device plugin and GPU manager for fractional GPU allocation on NVIDIA GPUs.

## Architecture

- **Device Plugin**: Advertises `example.com/gpu-slice` resources (6 slices per GPU)
- **GPU Manager**: Tracks slice allocation and enforces memory quotas
- **Sidecar Pattern**: Both components run in the same pod for reliable communication

## Quick Start (Ubuntu)

### Prerequisites

```bash
# Install Docker
sudo apt update
sudo apt install -y docker.io
sudo usermod -aG docker $USER
# Log out and back in

# Install NVIDIA drivers (if not already installed)
sudo apt install -y nvidia-driver-535
nvidia-smi  # Verify installation

# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt update
sudo apt install -y nvidia-docker2
sudo systemctl restart docker

# Install kubectl (if not already installed)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Verify Kubernetes cluster access
kubectl version --short
```

### Deployment

```bash
# Clone and enter repository
git clone <repo-url>
cd gpu-slice-allocation

# Make scripts executable
chmod +x deploy.sh verify.sh

# Deploy the system
./deploy.sh

# Verify deployment
./verify.sh

# Deploy test pod
kubectl apply -f k8s/gpu-pod-env.yaml

# Check test results
kubectl logs -f gpu-test-pod-env
```

### Multi-Pod Experiment

```bash
# Deploy 6 pods simultaneously
for i in {1..6}; do
    sed "s/gpu-test-pod-env/gpu-test-pod-$i/" k8s/gpu-pod-env.yaml | kubectl apply -f -
done

# Monitor GPU usage
watch -n 2 "kubectl get pods | grep gpu-test-pod; nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits"

# Collect metrics
./tools/collect_metrics.sh
```

## Components

### Device Plugin (`device-plugin/`)
- Go-based Kubernetes device plugin
- Advertises 6 GPU slices per node
- Calls GPU manager for slice allocation
- Injects environment variables into containers

### GPU Manager (`gpu-manager/`)
- Python daemon with REST API
- Tracks slice allocation table
- Monitors GPU usage with NVML
- Enforces memory quotas (prototype)

### Test Pods (`k8s/`)
- CuPy-based GPU workload
- Reads slice info from environment variables
- Matrix multiplication benchmark

## API Reference

### GPU Manager REST API

- `GET /health` - Health check
- `GET /status` - Current allocation status
- `POST /allocate` - Allocate slice to container
- `POST /release` - Release slice from container

### Environment Variables (Injected by Device Plugin)

- `GPU_SLICE_ID` - Assigned slice identifier (e.g., "slice0")
- `GPU_MEMORY_LIMIT_BYTES` - Memory limit in bytes
- `NVIDIA_VISIBLE_DEVICES` - GPU device visibility
- `NVIDIA_DRIVER_CAPABILITIES` - Driver capabilities

## Troubleshooting

### Common Issues

1. **Pods stuck in Pending**
   ```bash
   kubectl describe pod <pod-name>
   kubectl get nodes -o json | jq '.items[].status.allocatable'
   ```

2. **Device plugin not registering**
   ```bash
   kubectl logs -n kube-system -l app=gpu-sidecar -c gpu-slice-plugin
   sudo ls -la /var/lib/kubelet/device-plugins/
   ```

3. **GPU manager not responding**
   ```bash
   kubectl logs -n kube-system -l app=gpu-sidecar -c gpu-manager
   kubectl run test --rm -i --restart=Never --image=curlimages/curl -- curl -f http://127.0.0.1:5000/health
   ```

### Debug Commands

```bash
# Check system status
kubectl get pods -A -o wide
kubectl get nodes -o json | jq '.items[].status.allocatable'
nvidia-smi

# Check logs
kubectl logs -n kube-system -l app=gpu-sidecar -c gpu-slice-plugin
kubectl logs -n kube-system -l app=gpu-sidecar -c gpu-manager

# Check device plugin socket
kubectl exec -n kube-system <pod-name> -c gpu-slice-plugin -- ls -la /var/lib/kubelet/device-plugins/

# Test GPU manager API
kubectl run test --rm -i --restart=Never --image=curlimages/curl -- \
  curl -s http://127.0.0.1:5000/status
```

## Safety Notes

- This system is for development/testing only
- Uses privileged containers for GPU access
- Does not modify NVIDIA drivers or CUDA runtime
- Only implements logical slice allocation and monitoring
- No hardware GPU partitioning (MIG/vGPU)

## Architecture Decisions

1. **Sidecar Pattern**: Device plugin and GPU manager in same pod for reliable localhost communication
2. **Environment Variables**: Device plugin injects slice info via container environment
3. **REST API**: Simple HTTP API for allocation coordination
4. **NVML Monitoring**: Read-only GPU monitoring for quota enforcement
5. **No Hardware Partitioning**: Logical slices only, no MIG or driver modifications