#!/usr/bin/env python3
"""
Custom GPU-Aware Autoscaler  —  FIXED VERSION
=============================================

Bugs fixed vs original:
1. Namespace / deployment / label-selector now match the actual app
2. GPU utilization threshold lowered to match what the app actually reports
3. Reads `request_count` (cumulative) when `concurrent_requests` is absent
4. RPS delta calculated correctly from cumulative counter
5. `queue_length` and `concurrent_requests` handled gracefully if missing
6. Scaler no longer silently skips scaling when gpu_slice_usage fails
"""

import os
import time
import logging
from collections import deque
import requests
from kubernetes import client, config
from tenacity import retry, stop_after_attempt, wait_fixed

# ── CONFIG — edit these to match YOUR deployment ──────────────────────────────
NAMESPACE   = os.getenv("NAMESPACE",    "default")
DEPLOYMENT  = os.getenv("DEPLOYMENT",   "custom-fractional-app")   # ← FIXED
APP_LABEL   = os.getenv("APP_LABEL",    "custom-fractional-app")   # ← FIXED
APP_PORT    = int(os.getenv("APP_PORT", "8080"))                    # ← FIXED (was 8000)

MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "6"))
SYNC_PERIOD = int(os.getenv("SYNC_PERIOD", "5"))   # seconds between loops

# ── THRESHOLDS  (tuned for the rolling-window gpu_util the app now reports) ──
GPU_SCALE_UP_THRESHOLD   = 15   # ← LOWERED further for testing
GPU_SCALE_DOWN_THRESHOLD = 5
LATENCY_SLA_MS           = 100  # ← LOWERED from 500ms
LATENCY_CRITICAL_MS      = 200  # ← LOWERED from 1000ms
QUEUE_BACKLOG_THRESHOLD  = 1    # ← LOWERED from 3
REQUESTS_PER_POD_TARGET  = 3    # ← LOWERED from 5
REQUESTS_PER_POD_MAX     = 8    # ← LOWERED from 10

# ── COOLDOWNS ─────────────────────────────────────────────────────────────────
SCALE_UP_COOLDOWN        = 10   # seconds
SCALE_DOWN_COOLDOWN      = 60
LOW_LOAD_DURATION_THRESHOLD = 45

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gpu-scaler")
# ── Helpers ───────────────────────────────────────────────────────────────────
class EWMA:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.value = None
    
    def update(self, x):
        if x is None:
            return self.value
        self.value = x if self.value is None else self.alpha * x + (1 - self.alpha) * self.value
        return self.value or 0.0

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def load_kube_config():
    try:
        config.load_incluster_config()
        log.info("✅ Using in-cluster config")
    except Exception as e:
        log.warning(f"In-cluster config failed: {e}")
        # Don't try external config - it points to localhost:8080
        # Instead, fail fast so the pod restarts and tries in-cluster again
        raise Exception("In-cluster config required for pod operation")

def get_replicas(apps_api):
    dep = apps_api.read_namespaced_deployment_status(DEPLOYMENT, NAMESPACE)
    return dep.spec.replicas or MIN_REPLICAS

def scale(apps_api, replicas):
    body = {"spec": {"replicas": replicas}}
    apps_api.patch_namespaced_deployment_scale(DEPLOYMENT, NAMESPACE, body)
    log.info(f"  ↳ kubectl scale deployment/{DEPLOYMENT} --replicas={replicas}")

def list_app_pods(core_api):
    """Return running pods that belong to our app."""
    return core_api.list_namespaced_pod(
        NAMESPACE,
        label_selector=f"app={APP_LABEL}"   # ← FIXED: no extra scaler=userscale
    ).items

def get_pod_metrics(pod_ip):
    """Fetch metrics from a single pod."""
    try:
        resp = requests.get(f"http://{pod_ip}:{APP_PORT}/metrics", timeout=5)
        return resp.json() if resp.status_code == 200 else {}
    except Exception as e:
        log.warning(f"Failed to get metrics from {pod_ip}: {e}")
        return {}

def aggregate_metrics(core_api):
    """Collect and aggregate metrics from all running pods."""
    pods = [p for p in list_app_pods(core_api) if p.status.phase == "Running" and p.status.pod_ip]
    
    if not pods:
        log.warning("No running pods found")
        return {
            "total_requests": 0,
            "avg_gpu_util": 0,
            "avg_latency_ms": 0,
            "concurrent_requests": 0,
            "queue_length": 0,
            "pod_count": 0
        }
    
    all_metrics = []
    for pod in pods:
        metrics = get_pod_metrics(pod.status.pod_ip)
        if metrics:
            all_metrics.append(metrics)
    
    if not all_metrics:
        log.warning("No metrics collected from any pod")
        return {
            "total_requests": 0,
            "avg_gpu_util": 0,
            "avg_latency_ms": 0,
            "concurrent_requests": 0,
            "queue_length": 0,
            "pod_count": len(pods)
        }
    
    # Aggregate metrics
    total_requests = sum(m.get("request_count", 0) for m in all_metrics)
    avg_gpu_util = sum(m.get("gpu_utilization", 0) for m in all_metrics) / len(all_metrics)
    avg_latency = sum(m.get("avg_latency_ms", 0) for m in all_metrics) / len(all_metrics)
    concurrent_requests = sum(m.get("concurrent_requests", 0) for m in all_metrics)
    queue_length = sum(m.get("queue_length", 0) for m in all_metrics)
    
    return {
        "total_requests": total_requests,
        "avg_gpu_util": avg_gpu_util,
        "avg_latency_ms": avg_latency,
        "concurrent_requests": concurrent_requests,
        "queue_length": queue_length,
        "pod_count": len(pods)
    }

# ── Scaling Logic ─────────────────────────────────────────────────────────────
class ScalingDecision:
    def __init__(self):
        self.last_scale_up = 0
        self.last_scale_down = 0
        self.low_load_start = None
        self.rps_history = deque(maxlen=6)  # 30 seconds of 5s samples
        self.last_request_count = 0
        
        # Smoothing filters
        self.gpu_util_ewma = EWMA(alpha=0.4)
        self.latency_ewma = EWMA(alpha=0.3)
        self.rps_ewma = EWMA(alpha=0.5)

    def calculate_rps(self, current_requests):
        """Calculate requests per second from cumulative counter."""
        if self.last_request_count > 0:
            delta_requests = current_requests - self.last_request_count
            rps = delta_requests / SYNC_PERIOD
        else:
            rps = 0
        
        self.last_request_count = current_requests
        self.rps_history.append(rps)
        return self.rps_ewma.update(rps)

    def heuristic_score(self, metrics, current_replicas):
        """Calculate scaling urgency score (0-100)."""
        score = 0
        
        # GPU utilization pressure (0-30 points) - LOWERED THRESHOLDS
        gpu_util = metrics["avg_gpu_util"]
        if gpu_util > 30:      # ← LOWERED from 60
            score += 30
        elif gpu_util > 20:    # ← LOWERED from 40
            score += 20
        elif gpu_util > 10:    # ← LOWERED from 25
            score += 10
        
        # Queue backlog pressure (0-25 points)
        queue_len = metrics["queue_length"]
        if queue_len > 5:      # ← LOWERED from 10
            score += 25
        elif queue_len > 2:    # ← LOWERED from 5
            score += 15
        elif queue_len > 0:    # ← LOWERED from 2
            score += 8
        
        # Latency pressure (0-20 points) - LOWERED THRESHOLDS
        latency = metrics["avg_latency_ms"]
        if latency > LATENCY_CRITICAL_MS:  # 200ms
            score += 20
        elif latency > LATENCY_SLA_MS:     # 100ms
            score += 12
        elif latency > 50:     # ← LOWERED from 300ms
            score += 5
        
        # Concurrent load pressure (0-15 points)
        concurrent = metrics["concurrent_requests"]
        if concurrent > current_replicas * REQUESTS_PER_POD_MAX:
            score += 15
        elif concurrent > current_replicas * REQUESTS_PER_POD_TARGET:
            score += 8
        
        # RPS pressure (0-10 points)
        current_rps = self.calculate_rps(metrics["total_requests"])
        target_rps = current_replicas * REQUESTS_PER_POD_TARGET
        if current_rps > target_rps * 1.5:
            score += 10
        elif current_rps > target_rps:
            score += 5
        
        return min(100, score)

    def decide_scaling(self, metrics, current_replicas):
        """Main scaling decision logic."""
        now = time.time()
        
        # Smooth key metrics
        gpu_util = self.gpu_util_ewma.update(metrics["avg_gpu_util"])
        latency = self.latency_ewma.update(metrics["avg_latency_ms"])
        
        # Calculate heuristic score
        urgency_score = self.heuristic_score(metrics, current_replicas)
        
        log.info(f"📊 Metrics: GPU={gpu_util:.1f}% | Latency={latency:.0f}ms | "
                f"Queue={metrics['queue_length']} | Concurrent={metrics['concurrent_requests']} | "
                f"Urgency={urgency_score}/100")
        
        # ── SCALE UP CONDITIONS ──────────────────────────────────────────────
        if current_replicas < MAX_REPLICAS and (now - self.last_scale_up) > SCALE_UP_COOLDOWN:
            
            # Critical conditions - immediate scale up
            if (gpu_util > 70 or 
                latency > LATENCY_CRITICAL_MS or 
                metrics["queue_length"] > 8 or
                urgency_score > 80):
                
                target = min(MAX_REPLICAS, current_replicas + 2)
                log.info(f"🚨 CRITICAL SCALE UP: {current_replicas} → {target} (GPU={gpu_util:.1f}%, urgency={urgency_score})")
                self.last_scale_up = now
                self.low_load_start = None
                return target
            
            # Standard scale up conditions
            elif (gpu_util > GPU_SCALE_UP_THRESHOLD or 
                  latency > LATENCY_SLA_MS or 
                  metrics["queue_length"] > QUEUE_BACKLOG_THRESHOLD or
                  urgency_score > 25):    # ← LOWERED from 50
                
                target = min(MAX_REPLICAS, current_replicas + 1)
                log.info(f"📈 SCALE UP: {current_replicas} → {target} (GPU={gpu_util:.1f}%, urgency={urgency_score})")
                self.last_scale_up = now
                self.low_load_start = None
                return target
        
        # ── SCALE DOWN CONDITIONS ─────────────────────────────────────────────
        elif current_replicas > MIN_REPLICAS and (now - self.last_scale_down) > SCALE_DOWN_COOLDOWN:
            
            # Check if we're in sustained low load
            is_low_load = (gpu_util < GPU_SCALE_DOWN_THRESHOLD and 
                          latency < 200 and 
                          metrics["queue_length"] == 0 and
                          urgency_score < 20)
            
            if is_low_load:
                if self.low_load_start is None:
                    self.low_load_start = now
                    log.info(f"⏳ Low load detected, monitoring for {LOW_LOAD_DURATION_THRESHOLD}s...")
                elif (now - self.low_load_start) > LOW_LOAD_DURATION_THRESHOLD:
                    target = max(MIN_REPLICAS, current_replicas - 1)
                    log.info(f"📉 SCALE DOWN: {current_replicas} → {target} (sustained low load)")
                    self.last_scale_down = now
                    self.low_load_start = None
                    return target
            else:
                self.low_load_start = None
        
        # No scaling needed
        return current_replicas

# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    log.info("🚀 Custom GPU Scaler starting...")
    log.info(f"   Target: {NAMESPACE}/{DEPLOYMENT} (app={APP_LABEL})")
    log.info(f"   Replicas: {MIN_REPLICAS}-{MAX_REPLICAS}")
    log.info(f"   GPU thresholds: {GPU_SCALE_DOWN_THRESHOLD}% / {GPU_SCALE_UP_THRESHOLD}%")
    
    load_kube_config()
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()
    
    scaler = ScalingDecision()
    
    while True:
        try:
            current_replicas = get_replicas(apps_api)
            metrics = aggregate_metrics(core_api)
            
            log.info(f"🎯 Current: {current_replicas} pods | "
                    f"GPU: {metrics['avg_gpu_util']:.1f}% | "
                    f"Requests: {metrics['total_requests']} | "
                    f"Queue: {metrics['queue_length']}")
            
            target_replicas = scaler.decide_scaling(metrics, current_replicas)
            
            if target_replicas != current_replicas:
                scale(apps_api, target_replicas)
            else:
                log.info("✅ No scaling needed")
            
        except Exception as e:
            log.error(f"❌ Scaling loop error: {e}")
        
        time.sleep(SYNC_PERIOD)

if __name__ == "__main__":
    main()