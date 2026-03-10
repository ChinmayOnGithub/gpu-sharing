# Fractional GPU Allocation System

This system provides **true fractional GPU allocation** using memory-based slicing (not time-slicing) with Kubernetes autoscaling.

## 🎯 Objectives Achieved

1. ✅ **Fractional GPU Allocation**: Pods can request `example.com/gpu-slice` resources (1GB slices from 6GB RTX 3060)
2. ✅ **Auto Scaling**: Both HPA and custom scaler use fractional GPU resources for scaling decisions

## 🏗️ Architecture

### Core Components

1. **GPU Slice Device Plugin** (`gpu-slice-plugin`)
   - Advertises `example.com/gpu-slice: 6` resources
   - Allocates GPU memory slices to pods
   - Communicates with GPU Manager for slice tracking

2. **GPU Manager** (`gpu-manager`)
   - Tracks GPU slice allocations
   - Provides API for allocation/deallocation
   - Monitors GPU memory usage

3. **HPA with Fractional GPU** (`hpa-fractional-app`)
   - Uses `example.com/gpu-slice: 1` per pod
   - Scales based on CPU utilization (50% threshold)
   - Runs actual GPU workloads (matrix multiplication, image processing)

4. **Custom Fractional GPU Scaler** (`custom-fractional-app` + `custom-gpu-scaler`)
   - Uses `example.com/gpu-slice: 1` per pod
   - Scales based on GPU utilization (70% scale-up, 30% scale-down)
   - Custom scaling logic aware of GPU slice availability

## 🚀 Quick Start

### 1. Deploy the System
```bash
chmod +x deploy-fractional-system.sh
./deploy-fractional-system.sh
```

### 2. Set Up Port Forwarding
```bash
# Terminal 1
kubectl port-forward service/hpa-fractional-app 8003:8080

# Terminal 2  
kubectl port-forward service/custom-fractional-app 8004:8080
```

### 3. Run Comparison Demo
```bash
python3 demo-fractional.py
```

## 📊 Key Differences from Time-Slicing

| Aspect | Time-Slicing (Old) | Fractional GPU (This System) |
|--------|-------------------|------------------------------|
| **Resource Type** | `nvidia.com/gpu: 1` | `example.com/gpu-slice: 1` |
| **GPU Sharing** | Temporal (time-based) | Spatial (memory-based) |
| **Isolation** | Time slots | Memory regions |
| **Concurrency** | Sequential execution | True parallel execution |
| **Memory Limit** | Shared 6GB | Dedicated 1GB per slice |
| **Scaling Limit** | Limited by time slots | Limited by memory slices (6 max) |

## 🔍 Monitoring

### Check GPU Slice Usage
```bash
kubectl describe node jade | grep gpu-slice
```

### Monitor Scaling
```bash
watch 'kubectl get pods; echo; kubectl get hpa; echo; kubectl describe node jade | grep gpu-slice'
```

### View Logs
```bash
# Device plugin logs
kubectl logs -n kube-system -l app=gpu-sidecar -c gpu-slice-plugin

# GPU manager logs  
kubectl logs -n kube-system -l app=gpu-sidecar -c gpu-manager

# Custom scaler logs
kubectl logs -l app=custom-gpu-scaler
```

## 🧪 Testing GPU Workloads

### Test HPA App
```bash
curl "http://localhost:8003/gpu-work?type=matmul&size=1000"
```

### Test Custom App
```bash
curl "http://localhost:8004/gpu-work?type=image&size=800"
```

### Get Metrics
```bash
curl "http://localhost:8003/metrics"
curl "http://localhost:8004/metrics"
```

## 📈 Expected Results

### HPA Scaling
- Scales based on CPU utilization (50% threshold)
- Max 6 pods (limited by GPU slices)
- Each pod gets 1 GPU slice (1GB memory)

### Custom Scaling  
- Scales based on GPU utilization (70% up, 30% down)
- Faster scaling decisions (10s intervals vs HPA's 15s)
- GPU-aware scaling logic

### Performance Benefits
- **True Concurrency**: Multiple GPU workloads run simultaneously
- **Memory Isolation**: Each pod has dedicated 1GB GPU memory
- **Better Resource Utilization**: No time-slot waste
- **Predictable Performance**: Consistent memory allocation per pod

## 🔧 Configuration

### Adjust Scaling Thresholds

**HPA**: Edit `k8s/hpa-fractional-gpu.yaml`
```yaml
averageUtilization: 50  # CPU threshold
maxReplicas: 6          # Max pods (= GPU slices)
```

**Custom Scaler**: Edit scaling logic in `k8s/custom-fractional-scaler.yaml`
```python
if metrics['avg_gpu_util'] > 70:  # GPU threshold
    target_replicas = min(current_replicas + 1, MAX_REPLICAS)
```

### GPU Slice Configuration

Device plugin advertises slices based on GPU memory:
- RTX 3060 (6GB) → 6 slices of 1GB each
- Modify in `gpu-manager/gpu_manager.py` for different configurations

## 🎉 Success Criteria

✅ **Fractional Allocation Working**: Multiple pods with `example.com/gpu-slice: 1`  
✅ **Memory Isolation**: Each pod limited to 1GB GPU memory  
✅ **Concurrent Execution**: All pods run simultaneously (not time-sliced)  
✅ **Autoscaling**: Both HPA and custom scaler respond to load  
✅ **Resource Limits**: System respects 6-slice maximum  

This system demonstrates **true fractional GPU allocation** with memory-based isolation, enabling better resource utilization and predictable performance compared to time-slicing approaches.