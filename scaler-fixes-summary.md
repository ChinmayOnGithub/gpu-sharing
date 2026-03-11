# 🔧 Custom GPU Scaler Fixes Applied

## Bugs Identified and Fixed:

### **Bug 1: elif Logic Issue**
**Problem**: Aggressive scaling (GPU > 60%) was `elif`, so it never triggered if moderate scaling (GPU > 30%) was true first.

**Fix**: Moved aggressive scaling to be checked FIRST:
```python
# 1. Aggressive scale UP if very high GPU utilization (check this FIRST)
if metrics['avg_gpu_util'] > 60 and current_replicas < MAX_REPLICAS and gpu_slice_usage['available'] > 0:
    target_replicas = min(current_replicas + 2, MAX_REPLICAS)

# 2. Scale UP if moderate GPU utilization OR high request rate  
elif (metrics['avg_gpu_util'] > 30 or requests_per_second > 5) and ...:
    target_replicas = min(current_replicas + 1, MAX_REPLICAS)
```

### **Bug 2: Cumulative Request Count Issue**
**Problem**: `total_requests` was cumulative (75,033), always > 50, causing immediate scaling.

**Fix**: Implemented proper RPS calculation using deltas:
```python
# Track request counts for RPS calculation
last_request_count = 0
last_check_time = time.time()

# Calculate actual requests per second using delta
current_time = time.time()
time_delta = current_time - last_check_time
request_delta = metrics['total_requests'] - last_request_count
requests_per_second = request_delta / max(time_delta, 1)
```

### **Bug 3: Better Thresholds**
**Problem**: Request threshold of 50 was too low for cumulative counts.

**Fix**: Adjusted thresholds for RPS:
- Scale up: `requests_per_second > 5` (instead of total > 50)
- Scale down: `requests_per_second < 1` (instead of total < 10)

## **New Scaling Logic:**

```python
# 1. Aggressive scale UP: GPU > 60% → +2 pods
if metrics['avg_gpu_util'] > 60 and available_slices > 0:
    target_replicas = min(current + 2, MAX_REPLICAS)

# 2. Moderate scale UP: GPU > 30% OR RPS > 5 → +1 pod  
elif (metrics['avg_gpu_util'] > 30 or requests_per_second > 5) and available_slices > 0:
    target_replicas = min(current + 1, MAX_REPLICAS)

# 3. Scale DOWN: GPU < 15% AND RPS < 1 → -1 pod
elif metrics['avg_gpu_util'] < 15 and requests_per_second < 1:
    target_replicas = max(current - 1, MIN_REPLICAS)
```

## **Expected Behavior:**
- ✅ Proper RPS calculation (not cumulative)
- ✅ Aggressive scaling for high GPU load
- ✅ Respects GPU slice availability
- ✅ Better logging with RPS metrics
- ✅ No more stuck at 1 pod issue

## **To Apply:**
1. Rebuild scaler image: `docker build -t custom-gpu-scaler:latest .`
2. Import to k3s: `docker save custom-gpu-scaler:latest | sudo k3s ctr images import -`
3. Restart deployment: `kubectl rollout restart deployment custom-gpu-scaler`
4. Monitor logs: `kubectl logs -l app=custom-gpu-scaler --tail=20`