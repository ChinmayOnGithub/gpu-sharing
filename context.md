# Fractional GPU Allocation System - Complete Context

## Project Overview

This project implements a **Fractional GPU Allocation System** that enables multiple Kubernetes pods to concurrently share a single NVIDIA GPU through memory-based spatial partitioning. The system transforms traditional monolithic GPU allocation into fine-grained, slice-based resource sharing.

### Hardware Configuration
- **GPU**: NVIDIA RTX 3060 6GB GDDR6
- **CPU**: 12-core processor  
- **RAM**: 7GB system memory
- **OS**: Ubuntu Linux with k3s Kubernetes
- **NVIDIA Driver**: Version 550.163.01
- **CUDA**: Version 12.0

## System Architecture

### Core Components

1. **GPU Slice Device Plugin** (`device-plugin/`)
   - Go-based Kubernetes Device Plugin
   - Advertises 6 GPU slices as `example.com/gpu-slice` resources
   - Each slice represents 1GB of GPU memory (6GB total / 6 slices)
   - Handles allocation requests and container environment injection

2. **GPU Manager** (Sidecar in DaemonSet)
   - Python Flask REST API for slice management
   - Uses NVML for GPU monitoring and metrics collection
   - Tracks slice allocations and enforces quotas
   - Provides health status and diagnostics

3. **Sidecar DaemonSet Architecture**
   - Both device plugin and GPU manager run in same pod
   - Ensures reliable localhost communication
   - Deployed on every GPU-enabled node

4. **GPU Workload Applications** (`app/unified_app.py`)
   - FastAPI-based applications with CuPy GPU computations
   - Matrix multiplication workloads optimized for concurrent execution
   - Supports both HPA and Custom scaling modes
   - Implements adaptive batching for GPU efficiency

5. **Custom GPU-Aware Autoscaler** (`k8s/custom-scaler-image/gpu_scaler.py`)
   - Monitors actual GPU utilization and slice availability
   - Scales based on GPU metrics rather than CPU proxy
   - Implements intelligent scaling thresholds and cooldowns

## Current Implementation Status

### Working Features ✅
- **Resource Advertisement**: 6 GPU slices consistently advertised to Kubernetes
- **Concurrent Allocation**: Multiple pods successfully allocated GPU slices simultaneously  
- **Memory Isolation**: Each pod restricted to 1GB GPU memory segment (logical isolation)
- **Autoscaling Integration**: Both HPA and custom scaling respond to load changes
- **GPU Workload Execution**: Matrix multiplication workloads running on GPU slices
- **Metrics Collection**: Real-time GPU utilization, memory usage, and performance metrics

### Performance Results (Latest Test)
```
HPA Fractional GPU RESULTS:
Max Pods: 5
Max GPU Usage: 6/6
Throughput: 217.4 req/s
Success Rate: 100.0%
Scaling Events: 2

Custom Fractional GPU RESULTS:
Max Pods: 3
Max GPU Usage: 6/6
Throughput: 113.1 req/s
Success Rate: 100.0%
Scaling Events: 1
```

## Current Problems and Issues

### Problem 1: HPA Scaling Without GPU Need ❌

**Issue**: The HPA is scaling pods even when the application could be offloaded to CPU without needing GPU resources. This makes the system appear efficient but doesn't properly test the GPU-based logic.

**Root Cause Analysis**:
- HPA uses CPU utilization (50% threshold) as a proxy for GPU load
- CPU-based scaling doesn't consider actual GPU resource availability
- Applications can fall back to CPU processing when GPU is unavailable
- This creates false positive scaling scenarios

**Evidence from Code**:
```python
# In unified_app.py - CPU fallback logic
def process_matmul_batch_gpu(sizes: List[int]) -> List[float]:
    if not GPU_AVAILABLE or GPU_BROKEN:
        return process_matmul_batch_cpu(sizes)  # ← Falls back to CPU
```

**Impact**: 
- Testing doesn't validate true GPU resource constraints
- System appears to work but bypasses GPU allocation logic
- Performance metrics may be misleading

### Problem 2: Incorrect Slice Allocation Logic ❌

**Issue**: The number of slices assigned should be 1 per pod according to configuration, but this is not happening consistently.

**Root Cause Analysis**:

1. **Device Plugin Allocation Logic**:
```go
// In device-plugin/server.go
devices := make([]*pluginapi.Device, 6)
for i := 0; i < 6; i++ {
    devices[i] = &pluginapi.Device{
        ID:     fmt.Sprintf("slice%d", i),  // slice0, slice1, etc.
        Health: pluginapi.Healthy,
    }
}
```

2. **Resource Request Configuration**:
```yaml
# In k8s/custom-fractional-scaler.yaml
resources:
  requests:
    example.com/gpu-slice: 1  # ← Requests 1 slice
  limits:
    example.com/gpu-slice: 1  # ← Limits to 1 slice
```

3. **Allocation Request Processing**:
```go
// Device plugin processes allocation but may not enforce 1:1 mapping
sliceInfo, err := m.allocateSliceFromManager(req.DevicesIDs)
```

**Potential Issues**:
- GPU Manager may not properly track slice-to-pod mapping
- Multiple pods might be assigned to same slice
- Slice deallocation on pod termination may not work correctly
- Race conditions in allocation requests

### Problem 3: GPU Manager Communication Issues ⚠️

**Evidence from Logs**:
```
Allocation attempt 1 failed with status 0: <nil>
```

**Root Cause Analysis**:
- Device plugin retries allocation with backoff (up to 10 attempts)
- GPU Manager may not be responding correctly to allocation requests
- Network communication issues between device plugin and GPU manager
- GPU Manager REST API may have bugs in allocation logic

### Problem 4: MPS Configuration Issues ⚠️

**Current MPS Settings**:
```go
// In device-plugin/server.go
threadPct := 100 / 6                     // 16% compute per slice
memLimitMB := 6144 / 6                   // 1024 MB memory per slice
memLimitStr := fmt.Sprintf("0=%dm", memLimitMB)   // MPS format: "0=1024m"

envs := map[string]string{
    "CUDA_MPS_ACTIVE_THREAD_PERCENTAGE": fmt.Sprintf("%d", threadPct),
    "CUDA_MPS_PINNED_DEVICE_MEM_LIMIT": memLimitStr,
}
```

**Potential Issues**:
- MPS daemon may not be running or configured correctly
- Environment variables may not be properly enforced
- Memory limits may not be respected by applications
- Compute percentage limits may not work as expected

## Technical Architecture Details

### Resource Allocation Flow
1. Pod creation with `example.com/gpu-slice: 1` resource request
2. Kubernetes scheduler identifies nodes with available GPU slices
3. Device plugin receives allocation request via gRPC
4. GPU manager allocates specific slice ID and memory segment
5. Environment variables injected into container (slice ID, memory limit)
6. Container starts with GPU access restricted to allocated slice
7. GPU manager monitors usage and enforces quotas
8. Slice released upon pod termination

### Memory Isolation Mechanism
- **Logical Isolation**: Environment variable injection and application-level quota enforcement
- **Slice Assignment**: Each slice gets unique ID (slice0-slice5) and 1GB memory limit
- **Environment Variables**:
  - `GPU_SLICE_ID`: Unique slice identifier
  - `GPU_MEMORY_LIMIT_BYTES`: Memory limit (1GB per slice)
  - `NVIDIA_VISIBLE_DEVICES`: GPU device visibility
  - `CUDA_MPS_*`: MPS configuration for compute/memory limits

### Autoscaling Comparison

| Aspect | HPA | Custom Scaler |
|--------|-----|---------------|
| Trigger Metric | CPU utilization (50%) | GPU utilization (15% up, 5% down) |
| Scaling Logic | Standard K8s HPA | Custom GPU-aware logic |
| Resource Awareness | CPU proxy | Direct GPU metrics |
| Scaling Speed | Fast (CPU responsive) | Slower (GPU monitoring) |
| Accuracy | Low (proxy metric) | High (actual GPU usage) |

## Deployment Architecture

### DaemonSet Configuration
```yaml
# device-plugin/daemonset.yaml
spec:
  nodeSelector:
    accelerator: nvidia
  hostNetwork: true
  hostPID: true
  containers:
  - name: gpu-slice-device-plugin
    securityContext:
      privileged: true
```

### Application Deployment
```yaml
# k8s/custom-fractional-scaler.yaml
spec:
  runtimeClassName: nvidia
  nodeSelector:
    nvidia.com/gpu.present: "true"
  resources:
    requests:
      example.com/gpu-slice: 1
```

## Diagnostic Information

### System Status (Latest)
```
NAME                    READY   UP-TO-DATE   AVAILABLE   AGE
custom-fractional-app   1/1     1            1           30s
custom-gpu-scaler       1/1     1            1           30s
hpa-fractional-app      1/1     1            1           33s

GPU slices allocated: 2/6
```

### Port Forwarding
- HPA app: localhost:8003
- Custom app: localhost:8004

## Next Steps for Problem Resolution

### For Problem 1 (HPA CPU Fallback):
1. **Disable CPU Fallback**: Modify application to fail when GPU is unavailable
2. **GPU-Only Mode**: Add environment variable to force GPU-only execution
3. **Better Metrics**: Use GPU utilization directly for HPA instead of CPU

### For Problem 2 (Slice Allocation):
1. **Debug GPU Manager**: Add detailed logging to allocation/deallocation logic
2. **Verify Slice Tracking**: Ensure proper slice-to-pod mapping in GPU manager
3. **Test Allocation API**: Direct API calls to verify allocation behavior
4. **Check Resource Limits**: Verify Kubernetes resource enforcement

### For Problem 3 (Communication):
1. **Health Check GPU Manager**: Verify REST API is responding correctly
2. **Network Debugging**: Check localhost communication between containers
3. **Retry Logic**: Review and improve error handling in device plugin

### For Problem 4 (MPS Configuration):
1. **Verify MPS Daemon**: Check if MPS daemon is running on nodes
2. **Test MPS Limits**: Validate memory and compute limits are enforced
3. **Alternative Isolation**: Consider other isolation mechanisms if MPS fails

## Files and Directories

### Key Implementation Files
- `device-plugin/main.go` - Device plugin entry point
- `device-plugin/server.go` - Device plugin gRPC server and allocation logic
- `app/unified_app.py` - GPU workload application with FastAPI
- `k8s/custom-scaler-image/gpu_scaler.py` - Custom GPU-aware autoscaler
- `device-plugin/daemonset.yaml` - DaemonSet deployment configuration
- `k8s/custom-fractional-scaler.yaml` - Application and scaler deployments

### Deployment Scripts
- `build-and-deploy-all.sh` - Complete system deployment
- `clean-reset.sh` - System cleanup and reset
- `demo-fractional.py` - Performance testing framework

### Documentation
- `report/main.tex` - Complete technical report (LaTeX)
- `PROJECT_STRUCTURE.md` - Project structure documentation
- `README.md` - Main project documentation

This context document provides a comprehensive overview of the current system state, identified problems, and technical implementation details for further debugging and resolution.