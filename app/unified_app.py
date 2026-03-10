#!/usr/bin/env python3
"""
Unified FastAPI application - GPU AS SHARED ACCELERATOR ARCHITECTURE

ARCHITECTURE:
- Single physical GPU shared across multiple pods via time-slicing
- GPU is NOT a scalable resource (adding pods doesn't add GPU capacity)
- Focus: GPU efficiency and intelligent scheduling, not raw scaling

OPTIMIZATIONS:
1. Adaptive GPU Batching (UserScale only) - improves GPU efficiency
2. Moderate GPU workload per request - prevents saturation
3. Queue-based batch size adaptation (4/8/16 requests)
4. Batch time window: 12ms for request accumulation

WORKLOAD SIZING (GPU as shared accelerator):
- Request size: 1000 (moderate GPU work)
- CPU matrix: 600-1200 (allows concurrent execution)
- GPU matrix: 800-1400 (prevents individual pod saturation)
- Target: 80-95% GPU utilization across all pods

SCALER BEHAVIOR:
- HPA: Naive GPU usage (no batching, individual requests)
- UserScale: Optimized GPU usage (batching enabled, GPU-aware scheduling)

Workload controlled using WORKLOAD_TYPE and SCALER_TYPE environment variables.
"""

from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.responses import JSONResponse
import os
import time
import psutil
import numpy as np
from typing import Dict, Any, List, Optional
import threading
from concurrent.futures import ThreadPoolExecutor, Future
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
import uuid

# GPU runtime detection
try:
    import cupy as cp
    GPU_AVAILABLE = True
except Exception:
    cp = None
    GPU_AVAILABLE = False

GPU_BROKEN = False

# Real GPU metrics via pynvml
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_METRICS_AVAILABLE = True
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
except:
    GPU_METRICS_AVAILABLE = False
    GPU_HANDLE = None

# Config
WORKLOAD_TYPE = os.getenv("WORKLOAD_TYPE", "matmul").lower()  # Changed default to matmul
CPU_THREADS = max(1, int(os.getenv("CPU_THREADS", "8")))
PORT = int(os.getenv("PORT", "8000"))
SCALER_TYPE = os.getenv("SCALER_TYPE", "none").lower()  # "userscale" or "hpa" or "none"

# Adaptive Batching Configuration (UserScale only)
ENABLE_BATCHING = (SCALER_TYPE == "userscale")
BATCH_SIZE_SMALL = 4
BATCH_SIZE_MEDIUM = 8
BATCH_SIZE_LARGE = 16
BATCH_TIMEOUT_MS = 12  # 12ms batch timeout window

app = FastAPI(
    title=f"Userscale App - {WORKLOAD_TYPE.capitalize()} ({SCALER_TYPE.upper()})",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

log = logging.getLogger("userscale-app")

# Metrics tracking
start_time = time.time()
concurrent_requests = 0
latency_samples: deque = deque(maxlen=200)
latency_lock = threading.Lock()
request_count = 0
batch_count = 0

executor = ThreadPoolExecutor(max_workers=CPU_THREADS, thread_name_prefix="compute")


# Batching infrastructure (UserScale only)
@dataclass
class PendingRequest:
    """A pending request waiting to be batched"""
    request_id: str
    size: int
    timestamp: float
    future: Future = field(default_factory=lambda: Future())

pending_requests: deque = deque()
pending_lock = threading.Lock()
batch_processor_running = False


def record_latency(ms: float):
    with latency_lock:
        latency_samples.append(ms)


def get_avg_latency() -> float:
    with latency_lock:
        if not latency_samples:
            return 0.0
        return sum(latency_samples) / len(latency_samples)


def get_queue_length() -> int:
    """Get current pending request queue length"""
    with pending_lock:
        return len(pending_requests)


def get_adaptive_batch_size() -> int:
    """Determine batch size based on queue pressure"""
    queue_len = get_queue_length()
    if queue_len >= 15:
        return BATCH_SIZE_LARGE  # 16 requests
    elif queue_len >= 5:
        return BATCH_SIZE_MEDIUM  # 8 requests
    else:
        return BATCH_SIZE_SMALL  # 4 requests


def get_gpu_metrics() -> Dict[str, Any]:
    if not GPU_METRICS_AVAILABLE or not GPU_HANDLE:
        return {
            "gpu_utilization": 0.0,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 0,
            "gpu_memory_percent": 0.0,
            "gpu_temperature": 0
        }
    try:
        util = pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE)
        mem = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
        temp = pynvml.nvmlDeviceGetTemperature(GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)

        return {
            "gpu_utilization": float(util.gpu),
            "gpu_memory_used_mb": int(mem.used / (1024 * 1024)),
            "gpu_memory_total_mb": int(mem.total / (1024 * 1024)),
            "gpu_memory_percent": round((mem.used / mem.total) * 100, 1),
            "gpu_temperature": int(temp)
        }
    except:
        return {
            "gpu_utilization": 0.0,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 0,
            "gpu_memory_percent": 0.0,
            "gpu_temperature": 0
        }


# ================================
# BATCH PROCESSOR (UserScale only)
# ================================

def process_batch_worker():
    """Background worker that processes batches of requests"""
    global batch_count
    
    while batch_processor_running:
        time.sleep(BATCH_TIMEOUT_MS / 1000.0)  # Wait for batch window
        
        # Collect batch
        batch: List[PendingRequest] = []
        with pending_lock:
            if not pending_requests:
                continue
            
            target_size = get_adaptive_batch_size()
            while pending_requests and len(batch) < target_size:
                batch.append(pending_requests.popleft())
        
        if not batch:
            continue
        
        batch_count += 1
        
        # Process batch
        try:
            sizes = [req.size for req in batch]
            results = process_matmul_batch_gpu(sizes) if GPU_AVAILABLE else process_matmul_batch_cpu(sizes)
            
            # Resolve futures
            for req, result in zip(batch, results):
                req.future.set_result(result)
        except Exception as e:
            for req in batch:
                req.future.set_exception(e)


def start_batch_processor():
    """Start the batch processor thread"""
    global batch_processor_running
    if ENABLE_BATCHING and not batch_processor_running:
        batch_processor_running = True
        thread = threading.Thread(target=process_batch_worker, daemon=True, name="batch-processor")
        thread.start()


# ================================
# GPU-FRIENDLY WORKLOAD: MATRIX MULTIPLICATION
# ================================

def process_matmul_batch_cpu(sizes: List[int]) -> List[float]:
    """Process a batch of matrix multiplications on CPU"""
    results = []
    for size in sizes:
        # Matrix size optimized for single-GPU time-slicing
        matrix_size = max(600, min(size, 1200))
        
        # Generate matrices
        mat_a = np.random.rand(matrix_size, matrix_size).astype(np.float32)
        mat_b = np.random.rand(matrix_size, matrix_size).astype(np.float32)
        
        # Matrix multiplication
        result = np.dot(mat_a, mat_b)
        
        # Additional operations
        result = np.sin(result) + np.cos(result)
        result = np.sqrt(np.abs(result) + 1.0)
        result = np.tanh(result)
        
        results.append(float(np.sum(result[:10, :10])))
    
    return results


def process_matmul_batch_gpu(sizes: List[int]) -> List[float]:
    """Process a batch of matrix multiplications on GPU - OPTIMIZED FOR TIME-SLICING"""
    global GPU_BROKEN
    
    if not GPU_AVAILABLE or GPU_BROKEN:
        return process_matmul_batch_cpu(sizes)
    
    try:
        results = []
        batch_size = len(sizes)
        
        # Process all requests in batch with controlled GPU pressure
        for size in sizes:
            # GPU matrix size optimized for time-slicing (smaller to allow concurrent execution)
            matrix_size = max(800, min(size, 1400))
            
            # Create matrices on GPU
            mat_a = cp.random.rand(matrix_size, matrix_size, dtype=cp.float32)
            mat_b = cp.random.rand(matrix_size, matrix_size, dtype=cp.float32)
            
            # GPU matrix multiplication
            result = cp.matmul(mat_a, mat_b)
            
            # Reduced GPU operations for controlled utilization
            result = cp.sin(result) + cp.cos(result * 0.5)
            result = cp.sqrt(cp.abs(result) + 1.0)
            result = cp.tanh(result)
            
            # Extract result
            results.append(float(cp.sum(result[:10, :10]).get()))
            
            # Cleanup
            del mat_a, mat_b, result
        
        # Synchronize once for entire batch
        cp.cuda.Stream.null.synchronize()
        return results
        
    except Exception as e:
        GPU_BROKEN = True
        log.warning(f"GPU batch processing failed: {e}")
        return process_matmul_batch_cpu(sizes)


# ================================
# SINGLE REQUEST PROCESSING (HPA mode)
# ================================

def process_matmul_single_cpu(size: int) -> float:
    """Process single matrix multiplication on CPU"""
    return process_matmul_batch_cpu([size])[0]


def process_matmul_single_gpu(size: int) -> float:
    """Process single matrix multiplication on GPU"""
    return process_matmul_batch_gpu([size])[0]


# ================================
# API
# ================================

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_s": int(time.time() - start_time),
        "workload_type": WORKLOAD_TYPE,
        "gpu_available": GPU_AVAILABLE
    }


@app.get("/compute")
async def compute(
    size: int = Query(500, ge=100, le=2000)
):
    global concurrent_requests, request_count

    concurrent_requests += 1
    request_count += 1
    t0 = time.time()

    try:
        if WORKLOAD_TYPE == "matmul":
            # Matrix Multiplication Workload
            if ENABLE_BATCHING:
                # UserScale: Use adaptive batching
                request_id = str(uuid.uuid4())
                pending_req = PendingRequest(
                    request_id=request_id,
                    size=size,
                    timestamp=time.time()
                )
                
                with pending_lock:
                    pending_requests.append(pending_req)
                
                # Wait for batch processing
                result = await asyncio.get_event_loop().run_in_executor(
                    None, pending_req.future.result, 30  # 30s timeout
                )
                
                return {
                    "workload": "matmul_gpu_batched" if GPU_AVAILABLE else "matmul_cpu_batched",
                    "size": size,
                    "result": result,
                    "gpu_used": GPU_AVAILABLE,
                    "batched": True,
                    "scaler": SCALER_TYPE
                }
            else:
                # HPA: Process immediately without batching
                loop = asyncio.get_event_loop()
                if GPU_AVAILABLE:
                    result = await loop.run_in_executor(executor, process_matmul_single_gpu, size)
                    workload_used = "matmul_gpu"
                else:
                    result = await loop.run_in_executor(executor, process_matmul_single_cpu, size)
                    workload_used = "matmul_cpu"
                
                return {
                    "workload": workload_used,
                    "size": size,
                    "result": result,
                    "gpu_used": GPU_AVAILABLE,
                    "batched": False,
                    "scaler": SCALER_TYPE
                }
        else:
            return {
                "error": f"Unknown workload type: {WORKLOAD_TYPE}",
                "available": ["matmul"]
            }

    finally:
        dt = (time.time() - t0) * 1000
        record_latency(dt)
        concurrent_requests -= 1


@app.get("/metrics")
def metrics():
    cpu_percent = psutil.cpu_percent(interval=0.0)
    mem = psutil.virtual_memory()
    avg_latency = get_avg_latency()
    queue_len = get_queue_length()
    gpu = get_gpu_metrics()

    return JSONResponse({
        "gpu_utilization": gpu["gpu_utilization"],
        "avg_latency_ms": avg_latency,
        "gpu_memory_used_mb": gpu["gpu_memory_used_mb"],
        "gpu_memory_total_mb": gpu["gpu_memory_total_mb"],
        "gpu_memory_percent": gpu["gpu_memory_percent"],
        "gpu_temperature": gpu["gpu_temperature"],
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "request_count": request_count,
        "batch_count": batch_count,
        "uptime_s": int(time.time() - start_time),
        "workload_type": WORKLOAD_TYPE,
        "gpu_available": GPU_AVAILABLE,
        "concurrent_requests": concurrent_requests,
        "queue_length": queue_len,
        "batching_enabled": ENABLE_BATCHING,
        "scaler_type": SCALER_TYPE
    })


if __name__ == "__main__":
    import uvicorn
    
    # Start batch processor if enabled
    start_batch_processor()

    uvicorn.run(
        "app.unified_app:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=1,
        access_log=False,
        log_level="warning"
    )
