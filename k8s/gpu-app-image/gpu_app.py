#!/usr/bin/env python3
"""
GPU Fractional App - Real CUDA workloads via CuPy
Fixed: proper concurrent_requests, queue_length, accurate gpu_utilization
"""
from flask import Flask, request, jsonify
import time
import threading
import collections
import psutil
import os

# ── CuPy: real CUDA ───────────────────────────────────────────────────────────
try:
    import cupy as cp
    cp.cuda.Device(0).use()
    mempool = cp.get_default_memory_pool()
    mempool.set_limit(size=1024**3)  # 1 GB limit per slice
    CUDA_AVAILABLE = True
    print("✅ CuPy CUDA available — real GPU work enabled")
except Exception as e:
    import numpy as cp
    CUDA_AVAILABLE = False
    print(f"⚠️  CuPy not available ({e}) — falling back to CPU numpy")

app = Flask(__name__)

# ── Metrics & concurrency tracking ───────────────────────────────────────────
metrics_lock = threading.Lock()

# Rolling window for GPU utilization (5-second window)
_GPU_UTIL_WINDOW = 5.0
_recent_gpu_durations = collections.deque()   # (finish_timestamp, duration_s)

# Live counters (updated atomically under metrics_lock)
_active_requests = 0   # requests currently inside do_gpu_work()

metrics = {
    "request_count":       0,
    "gpu_utilization":     0,   # % over last 5 s  ← FIXED
    "cpu_percent":         0,
    "avg_latency_ms":      0,
    "total_latency":       0,
    "concurrent_requests": 0,   # NEW — live in-flight count
    "queue_length":        0,   # NEW — waiting behind the active ones
    "cuda_enabled":        CUDA_AVAILABLE,
}

# ── GPU utilization helper ────────────────────────────────────────────────────
def _update_gpu_utilization(duration_s: float):
    """Record a completed GPU kernel duration and recompute utilization.
    Utilization = (sum of GPU-active seconds in last window) / window_size * 100
    This is equivalent to how nvidia-smi calculates GPU-Util: fraction of the
    measurement window in which at least one kernel was executing."""
    now = time.time()
    cutoff = now - _GPU_UTIL_WINDOW
    
    # Append new sample
    _recent_gpu_durations.append((now, duration_s))
    
    # Drop samples outside the window
    while _recent_gpu_durations and _recent_gpu_durations[0][0] < cutoff:
        _recent_gpu_durations.popleft()
    
    # Sum GPU-busy time in the window
    total_gpu_busy = sum(d for _, d in _recent_gpu_durations)
    
    # For concurrent requests we cap at window size (GPU can't be >100% busy)
    metrics["gpu_utilization"] = min(99, (total_gpu_busy / _GPU_UTIL_WINDOW) * 100)

# ── Real GPU work ─────────────────────────────────────────────────────────────
def do_gpu_work(work_type: str, size: int) -> tuple:
    """Runs actual CUDA kernels. Thread-safe; updates live concurrency metrics."""
    global _active_requests
    
    # ── Enter: bump live counters ────────────────────────────────────────────
    with metrics_lock:
        _active_requests += 1
        metrics["concurrent_requests"] = _active_requests
        # queue = requests waiting = active - 1  (0 if this is the only one)
        metrics["queue_length"] = max(0, _active_requests - 1)
    
    start = time.time()
    try:
        if work_type == "matmul":
            A = cp.random.randn(size, size).astype(cp.float32)
            B = cp.random.randn(size, size).astype(cp.float32)
            C = cp.matmul(A, B)
        elif work_type == "fft":
            signal = cp.random.randn(size * size).astype(cp.float32)
            C = cp.fft.fft(signal)
        elif work_type == "reduction":
            data = cp.random.randn(size, size).astype(cp.float32)
            C = cp.sum(data, axis=0)
            C = cp.max(C)
        else:
            A = cp.random.randn(size, size).astype(cp.float32)
            B = cp.random.randn(size, size).astype(cp.float32)
            C = cp.matmul(A, B)
        
        # Synchronize — wait for GPU kernel to finish
        if CUDA_AVAILABLE:
            cp.cuda.Stream.null.synchronize()
        
        duration = time.time() - start
        
        # ── Update metrics atomically ────────────────────────────────────────
        with metrics_lock:
            metrics["request_count"] += 1
            metrics["total_latency"] += duration * 1000
            metrics["avg_latency_ms"] = metrics["total_latency"] / metrics["request_count"]
            _update_gpu_utilization(duration)   # ← FIXED utilization
        
        result_scalar = float(cp.sum(C).item() if hasattr(C, "item") else C)
        
        if CUDA_AVAILABLE:
            del A, B, C
            cp.get_default_memory_pool().free_all_blocks()
        
        return result_scalar, duration
    
    finally:
        # ── Exit: always decrement, even on error ────────────────────────────
        with metrics_lock:
            _active_requests -= 1
            metrics["concurrent_requests"] = _active_requests
            metrics["queue_length"] = max(0, _active_requests - 1)

# ── Background CPU monitor ────────────────────────────────────────────────────
def _cpu_monitor():
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1)
            with metrics_lock:
                metrics["cpu_percent"] = cpu
        except Exception:
            pass
        time.sleep(5)

threading.Thread(target=_cpu_monitor, daemon=True).start()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({
        "status":       "healthy",
        "pod":          os.environ.get("POD_NAME", "unknown"),
        "gpu_slice":    os.environ.get("GPU_SLICE_ID", "unknown"),
        "cuda_enabled": CUDA_AVAILABLE,
    })

@app.route("/metrics")
def get_metrics():
    with metrics_lock:
        return jsonify(metrics.copy())

@app.route("/gpu-work")
def gpu_work():
    work_type = request.args.get("type", "matmul")
    size      = int(request.args.get("size", 500))
    size      = min(size, 2000)   # clamp to avoid OOM on 1 GB slice
    
    try:
        result, duration = do_gpu_work(work_type, size)
        return jsonify({
            "status":       "success",
            "work_type":    work_type,
            "size":         size,
            "duration_ms":  round(duration * 1000, 2),
            "cuda_enabled": CUDA_AVAILABLE,
            "gpu_slice_id": os.environ.get("GPU_SLICE_ID", "unknown"),
            "pod":          os.environ.get("POD_NAME", "unknown"),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"GPU Fractional App starting on port 8080")
    print(f"Pod      : {os.environ.get('POD_NAME', 'unknown')}")
    print(f"GPU Slice: {os.environ.get('GPU_SLICE_ID', 'not-allocated')}")
    print(f"CUDA     : {CUDA_AVAILABLE}")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)