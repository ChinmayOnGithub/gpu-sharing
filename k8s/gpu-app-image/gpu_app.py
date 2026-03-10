#!/usr/bin/env python3
"""
GPU Fractional App - Real CUDA workloads via CuPy
Shows actual GPU utilization in nvidia-smi.
"""
from flask import Flask, request, jsonify
import time
import threading
import psutil
import os

# ── CuPy: real CUDA ───────────────────────────────────────────────────────────
try:
    import cupy as cp
    cp.cuda.Device(0).use()   # select GPU 0
    CUDA_AVAILABLE = True
    print("✅ CuPy CUDA available — real GPU work enabled")
except Exception as e:
    import numpy as cp        # fallback to numpy (same API)
    CUDA_AVAILABLE = False
    print(f"⚠️  CuPy not available ({e}) — falling back to CPU numpy")

app = Flask(__name__)

# ── Metrics ───────────────────────────────────────────────────────────────────
metrics = {
    "request_count":  0,
    "gpu_utilization": 0,
    "cpu_percent":    0,
    "avg_latency_ms": 0,
    "total_latency":  0,
    "cuda_enabled":   CUDA_AVAILABLE,
}
metrics_lock = threading.Lock()

# ── Real GPU work ─────────────────────────────────────────────────────────────
def do_gpu_work(work_type: str, size: int) -> tuple:
    """Runs actual CUDA kernels via CuPy.
    Falls back to NumPy automatically if no GPU is present."""
    start = time.time()
    
    if work_type == "matmul":
        # Matrix multiplication — the classic GPU benchmark
        # size=500  → 500×500 matrices  (light)
        # size=1000 → 1000×1000 matrices (medium)
        # size=2000 → 2000×2000 matrices (heavy)
        A = cp.random.randn(size, size, dtype=cp.float32)
        B = cp.random.randn(size, size, dtype=cp.float32)
        C = cp.dot(A, B)          # CUDA DGEMM kernel
        
    elif work_type == "fft":
        # FFT on a large signal — stresses GPU memory bandwidth
        signal = cp.random.randn(size * size, dtype=cp.float32)
        C = cp.fft.fft(signal)
        
    elif work_type == "reduction":
        # Sum/max reduction — tests GPU parallelism
        data = cp.random.randn(size, size, dtype=cp.float32)
        C = cp.sum(data, axis=0)
        C = cp.max(C)
        
    else:
        # Default: matmul
        A = cp.random.randn(size, size, dtype=cp.float32)
        B = cp.random.randn(size, size, dtype=cp.float32)
        C = cp.dot(A, B)
    
    # Synchronize — wait for GPU to finish before measuring time
    if CUDA_AVAILABLE:
        cp.cuda.Stream.null.synchronize()
    
    duration = time.time() - start
    
    # Update metrics
    with metrics_lock:
        metrics["request_count"] += 1
        metrics["total_latency"] += duration * 1000
        metrics["avg_latency_ms"] = (metrics["total_latency"] / metrics["request_count"])
        
        # Real GPU util isn't readable from Python without NVML,
        # but we know work happened — report based on actual duration
        metrics["gpu_utilization"] = min(95, duration * 500)
    
    return float(cp.sum(C).item() if hasattr(C, 'item') else C), duration

# ── Background CPU metrics ────────────────────────────────────────────────────
def _cpu_monitor():
    while True:
        try:
            with metrics_lock:
                metrics["cpu_percent"] = psutil.cpu_percent(interval=1)
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
    
    # Clamp size to avoid OOM on 1GB slice
    size = min(size, 2000)
    
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