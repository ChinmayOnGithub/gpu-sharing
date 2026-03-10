# GPU Manager Daemon

A Python-based GPU slice manager for fractional GPU allocation on Kubernetes.

## Features

- **Safe Monitoring**: Read-only GPU monitoring using NVML
- **Slice Management**: 6 GPU slices (1GB each for RTX 3060 6GB)
- **REST API**: Allocate/release slices via HTTP API
- **Process Tracking**: Monitor GPU processes and memory usage
- **Quota Enforcement**: Alert on memory quota violations
- **Kubernetes Ready**: DaemonSet deployment included

## Quick Start

### Local Testing (Windows/Linux)

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python gpu_manager.py

# Test in another terminal
python test_client.py
```

### Kubernetes Deployment

```bash
# Make scripts executable
chmod +x *.sh

# Deploy to Kubernetes
./deploy.sh

# Test the API
./test.sh
```

## API Endpoints

### POST /allocate
Allocate GPU slices to a pod:
```bash
curl -X POST http://localhost:8080/allocate \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "my-pod", "slices": 2}'
```

### POST /release
Release GPU slices from a pod:
```bash
curl -X POST http://localhost:8080/release \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "my-pod"}'
```

### GET /status
Get current GPU status and allocation table:
```bash
curl http://localhost:8080/status
```

### GET /health
Health check:
```bash
curl http://localhost:8080/health
```

## Slice Allocation Table

Default configuration for RTX 3060 6GB:

| Slice ID | Memory Limit | Status | Pod Name |
|----------|--------------|--------|----------|
| slice0   | 1GB         | Available | - |
| slice1   | 1GB         | Available | - |
| slice2   | 1GB         | Available | - |
| slice3   | 1GB         | Available | - |
| slice4   | 1GB         | Available | - |
| slice5   | 1GB         | Available | - |

## Safety

This GPU manager is completely safe:
- ✅ Read-only GPU monitoring
- ✅ No driver modifications
- ✅ No interference with existing applications
- ✅ Graceful degradation on errors

See [SAFETY.md](SAFETY.md) for detailed safety information.

## Configuration

Environment variables:
- `GPU_MEMORY_GB`: Total GPU memory (default: 6)
- `API_PORT`: API server port (default: 8080)
- `LOG_LEVEL`: Logging level (default: INFO)

## Requirements

- Python 3.10+
- NVIDIA GPU with drivers installed
- NVIDIA Management Library (NVML) access
- Kubernetes cluster (for K8s deployment)

## Troubleshooting

1. **NVML initialization failed**: Check NVIDIA drivers are installed
2. **Permission denied**: Run with appropriate privileges for GPU access
3. **API not responding**: Check port 8080 is available
4. **No GPU found**: Verify `nvidia-smi` works

## Integration with Device Plugin

This GPU manager works alongside the Kubernetes device plugin:

1. **Device Plugin**: Advertises `example.com/gpu-slice` resources
2. **GPU Manager**: Tracks actual allocation and enforces quotas
3. **Pods**: Request slices via resource limits

Example pod requesting 2 GPU slices:
```yaml
resources:
  limits:
    example.com/gpu-slice: 2
```