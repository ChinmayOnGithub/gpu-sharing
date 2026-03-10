#!/usr/bin/env python3
"""
GPU Slice Manager - Fixed Version
Handles allocation/deallocation of GPU slices for the Kubernetes device plugin.
NVML is optional - falls back to simulation mode if libnvidia-ml.so is not available.
"""

import os
import json
import threading
import logging
from flask import Flask, request, jsonify

# ── NVML: optional import ──────────────────────────────────────────────────────
try:
    import pynvml
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
    logging.info("NVML initialized successfully - real GPU monitoring enabled")
except Exception as e:
    NVML_AVAILABLE = False
    logging.warning(f"NVML not available ({e}) - running in simulation mode. "
                   "Slice tracking still works; GPU memory monitoring disabled.")

# ── Configuration ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

app = Flask(__name__)

# Parse total GPU memory from env (e.g. "6GB" or "6144MB")
_raw_mem = os.environ.get("GPU_TOTAL_MEMORY", "6GB").upper().strip()
if _raw_mem.endswith("GB"):
    TOTAL_MEMORY_MB = int(_raw_mem[:-2]) * 1024
elif _raw_mem.endswith("MB"):
    TOTAL_MEMORY_MB = int(_raw_mem[:-2])
else:
    TOTAL_MEMORY_MB = 6144  # default 6 GB

NUM_SLICES   = int(os.environ.get("NUM_SLICES", "6"))
SLICE_MEM_MB = TOTAL_MEMORY_MB // NUM_SLICES   # e.g. 1024 MB per slice

# ── In-memory allocation state ─────────────────────────────────────────────────
_lock          = threading.Lock()
# slice_id (str) → container_id (str) | None
_slices: dict  = {f"slice{i}": None for i in range(NUM_SLICES)}

logging.info(f"GPU Slice Manager starting: "
            f"{NUM_SLICES} slices × {SLICE_MEM_MB} MB = {TOTAL_MEMORY_MB} MB total")

# ── Helper ─────────────────────────────────────────────────────────────────────
def _get_real_gpu_memory_used_mb() -> int:
    """Returns GPU memory used in MB via NVML, or -1 if unavailable."""
    if not NVML_AVAILABLE:
        return -1
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info   = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return info.used // (1024 * 1024)
    except Exception:
        return -1

def _get_gpu_name() -> str:
    """Get GPU name, handling both string and bytes return types."""
    if not NVML_AVAILABLE:
        return "Simulation Mode"
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        # Handle both string and bytes return types for compatibility
        if isinstance(gpu_name, bytes):
            gpu_name = gpu_name.decode('utf-8')
        return gpu_name
    except Exception as e:
        logging.warning(f"Could not get GPU name: {e}")
        return "Unknown GPU"

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    used   = sum(1 for v in _slices.values() if v is not None)
    free   = NUM_SLICES - used
    gpu_mb = _get_real_gpu_memory_used_mb()
    
    return jsonify({
        "status":       "healthy",
        "nvml_enabled": NVML_AVAILABLE,
        "gpu_name":     _get_gpu_name(),
        "slices": {
            "total": NUM_SLICES,
            "used":  used,
            "free":  free,
        },
        "gpu_memory_used_mb": gpu_mb if gpu_mb >= 0 else "unavailable",
    }), 200

@app.route("/allocate", methods=["POST"])
def allocate():
    """Body (JSON): { "container_id": "<id>", "slice_id": "<slice_name>" }
    The device plugin sends the slice_id it chose (e.g. "slice3").
    """
    data = request.get_json(force=True, silent=True) or {}
    container_id = data.get("container_id", "").strip()
    slice_id     = data.get("slice_id", "").strip()
    
    if not container_id or not slice_id:
        return jsonify({"error": "container_id and slice_id are required"}), 400
    
    with _lock:
        if slice_id not in _slices:
            return jsonify({"error": f"Unknown slice: {slice_id}"}), 400
        
        if _slices[slice_id] is not None:
            existing = _slices[slice_id]
            if existing == container_id:
                # Idempotent - same container re-requesting same slice is OK
                logging.info(f"Idempotent re-allocation: {slice_id} → {container_id}")
                return jsonify({
                    "status":     "already_allocated",
                    "slice_id":   slice_id,
                    "memory_mb":  SLICE_MEM_MB,
                }), 200
            return jsonify({"error": f"Slice {slice_id} already held by {existing}"}), 409  # Conflict
        
        _slices[slice_id] = container_id
    
    logging.info(f"Allocated {slice_id} ({SLICE_MEM_MB} MB) → container {container_id}")
    return jsonify({
        "status":    "allocated",
        "slice_id":  slice_id,
        "memory_mb": SLICE_MEM_MB,
    }), 200

@app.route("/deallocate", methods=["POST"])
def deallocate():
    """Body (JSON): { "container_id": "<id>" }
    Releases ALL slices held by this container_id.
    """
    data         = request.get_json(force=True, silent=True) or {}
    container_id = data.get("container_id", "").strip()
    
    if not container_id:
        return jsonify({"error": "container_id is required"}), 400
    
    freed = []
    with _lock:
        for sid, holder in _slices.items():
            if holder == container_id:
                _slices[sid] = None
                freed.append(sid)
    
    logging.info(f"Deallocated slices {freed} from container {container_id}")
    return jsonify({"status": "deallocated", "slices_freed": freed}), 200

@app.route("/status", methods=["GET"])
def status():
    with _lock:
        snapshot = dict(_slices)
    
    allocations = [
        {"slice_id": sid, "container_id": cid, "memory_mb": SLICE_MEM_MB}
        for sid, cid in snapshot.items()
        if cid is not None
    ]
    free_slices = [sid for sid, cid in snapshot.items() if cid is None]
    
    return jsonify({
        "total_slices":  NUM_SLICES,
        "slice_mem_mb":  SLICE_MEM_MB,
        "nvml_enabled":  NVML_AVAILABLE,
        "gpu_name":      _get_gpu_name(),
        "allocations":   allocations,
        "free_slices":   free_slices,
        "gpu_memory_used_mb": _get_real_gpu_memory_used_mb(),
    }), 200

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", "5000"))
    gpu_name = _get_gpu_name()
    logging.info(f"GPU Manager starting on 0.0.0.0:{port}")
    logging.info(f"GPU: {gpu_name}")
    logging.info(f"NVML Available: {NVML_AVAILABLE}")
    app.run(host="0.0.0.0", port=port, threaded=True)