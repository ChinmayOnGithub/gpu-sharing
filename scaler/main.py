import os
import time
import logging
from collections import deque

import requests
from kubernetes import client, config
from tenacity import retry, stop_after_attempt, wait_fixed


# =============================
# CONFIG
# =============================

def getenv(name, default):
    return os.getenv(name, default)

NAMESPACE = getenv("NAMESPACE", "userscale")
DEPLOYMENT = getenv("DEPLOYMENT", "userscale-app")
SERVICE_NAME = getenv("SERVICE_NAME", "userscale-app")
APP_PORT = int(getenv("APP_PORT", "8000"))

# =============================
# HEURISTIC SCALING ENGINE
# GPU AS SHARED ACCELERATOR ARCHITECTURE
# =============================
#
# ARCHITECTURE PRINCIPLE:
# - Single physical GPU shared across all pods via time-slicing
# - GPU is NOT a scalable resource (more pods ≠ more GPU capacity)
# - Focus: GPU efficiency and intelligent scheduling
#
# SCALING STRATEGY:
# - Scale based on GPU-aware metrics (queue, GPU util, latency, growth)
# - Heuristic scoring: 45% queue + 30% GPU + 15% latency + 10% growth
# - Sync period: 3 seconds (aggressive monitoring)
# - Target: 8 requests/pod, max 12 before forced scale-up
#
# =============================

SYNC_PERIOD = int(getenv("SYNC_PERIOD", "3"))  # 3 seconds - aggressive monitoring

MIN_REPLICAS = int(getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(getenv("MAX_REPLICAS", "6")) 

# HEURISTIC THRESHOLDS - OPTIMIZED FOR SHARED GPU ACCELERATOR
GPU_SCALE_UP_THRESHOLD = 70      # GPU > 70% triggers scale consideration
GPU_SCALE_DOWN_THRESHOLD = 30    # GPU < 30% allows scale down
LATENCY_SLA_MS = 500             # Target latency SLA
LATENCY_CRITICAL_MS = 1000       # Critical latency threshold
QUEUE_BACKLOG_THRESHOLD = 5      # Queue length threshold
REQUESTS_PER_POD_TARGET = 8      # Target concurrent requests per pod
REQUESTS_PER_POD_MAX = 12        # Maximum before forced scale-up

# COOLDOWNS
SCALE_UP_COOLDOWN = 3      # Very fast scale-up response
SCALE_DOWN_COOLDOWN = 45   # Conservative scale-down

# LOW LOAD TRACKING
LOW_LOAD_DURATION_THRESHOLD = 40  # 40 seconds of low load before scale down

# CAPACITY-BASED SCALING
CAPACITY_SAFETY_MARGIN = 1.15     # 15% safety margin for capacity planning

# PREDICTIVE SCALING
RAPID_GROWTH_THRESHOLD = 0.5     # 50% growth triggers predictive scaling

# PREDICTIVE ANALYSIS
HISTORY_SIZE = 20          # Track last 60 seconds (20 * 3s)
EMA_ALPHA = 0.3            # Exponential moving average weight

CSV_LOGGING = getenv("CSV_LOG", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("userscale-scaler")


# =============================
# HELPERS
# =============================

class EWMA:
    """Exponential Weighted Moving Average for smoothing metrics"""
    def __init__(self, alpha=EMA_ALPHA):
        self.alpha = alpha
        self.value = None

    def update(self, x):
        if x is None:
            return self.value
        self.value = x if self.value is None else self.alpha * x + (1 - self.alpha) * self.value
        return self.value


class RequestRateTracker:
    """Track request rate and predict future load"""
    def __init__(self, window_size=HISTORY_SIZE):
        self.history = deque(maxlen=window_size)
        self.timestamps = deque(maxlen=window_size)
    
    def add(self, count):
        self.history.append(count)
        self.timestamps.append(time.time())
    
    def get_rate(self):
        """Get requests per second"""
        if len(self.history) < 2:
            return 0.0
        time_span = self.timestamps[-1] - self.timestamps[0]
        if time_span == 0:
            return 0.0
        total_requests = sum(self.history)
        return total_requests / time_span
    
    def get_growth_rate(self):
        """Get growth rate (percentage change)"""
        if len(self.history) < 6:
            return 0.0
        recent = sum(list(self.history)[-3:]) / 3
        older = sum(list(self.history)[-6:-3]) / 3
        if older == 0:
            return 0.0
        return (recent - older) / older
    
    def predict_load(self):
        """Predict future load using EMA"""
        if len(self.history) < 3:
            return self.history[-1] if self.history else 0
        
        # Simple EMA prediction
        weights = [0.5, 0.3, 0.2]
        recent = list(self.history)[-3:]
        return sum(w * v for w, v in zip(weights, recent))


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def load_kube_config():
    try:
        config.load_incluster_config()
    except:
        config.load_kube_config()


def get_replicas(api):
    dep = api.read_namespaced_deployment_status(DEPLOYMENT, NAMESPACE)
    return dep.spec.replicas or MIN_REPLICAS


def list_pods(core):
    return core.list_namespaced_pod(
        NAMESPACE,
        label_selector=f"app={SERVICE_NAME},scaler=userscale"
    ).items


def fetch_metrics(pods):
    """Fetch metrics from all pods"""
    gpu_vals, latency_vals, cpu_vals = [], [], []
    total_concurrent = 0
    total_requests = 0
    queue_length = 0

    for p in pods:
        ip = p.status.pod_ip
        if not ip:
            continue

        try:
            r = requests.get(f"http://{ip}:{APP_PORT}/metrics", timeout=2).json()
            total_concurrent += int(r.get("concurrent_requests", 0))
            total_requests += int(r.get("request_count", 0))
            queue_length += int(r.get("queue_length", 0))

            if "gpu_utilization" in r and r["gpu_utilization"] > 0:
                gpu_vals.append(float(r["gpu_utilization"]))
            
            if "cpu_percent" in r:
                cpu_vals.append(float(r["cpu_percent"]))

            if "avg_latency_ms" in r and r["avg_latency_ms"] > 0:
                latency_vals.append(float(r["avg_latency_ms"]))

        except Exception:
            continue

    return {
        "concurrent_requests": total_concurrent,
        "total_requests": total_requests,
        "queue_length": queue_length,
        "gpu_avg": sum(gpu_vals) / len(gpu_vals) if gpu_vals else 0,
        "gpu_max": max(gpu_vals) if gpu_vals else 0,
        "cpu_avg": sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0,
        "latency_avg": sum(latency_vals) / len(latency_vals) if latency_vals else 0,
        "latency_max": max(latency_vals) if latency_vals else 0,
    }


def decide_scale_heuristic(current_replicas, metrics, request_tracker, last_scale_up, last_scale_down, low_load_start, peak_request_rate):
    """
    IMPROVED HEURISTIC SCALING ENGINE WITH CAPACITY-BASED AND PREDICTIVE SCALING
    
    Priority:
    1. Capacity-based scaling (immediate response to overload)
    2. Predictive scaling (proactive response to growth)
    3. Heuristic scoring (balanced decision making)
    4. Downscaling (conservative resource reduction)
    """
    current_time = time.time()
    can_scale_up = (current_time - last_scale_up) >= SCALE_UP_COOLDOWN
    can_scale_down = (current_time - last_scale_down) >= SCALE_DOWN_COOLDOWN
    
    # Calculate per-pod metrics
    requests_per_pod = metrics["concurrent_requests"] / max(current_replicas, 1)
    queue_per_pod = metrics["queue_length"] / max(current_replicas, 1)
    
    # Get predictive metrics
    request_growth = request_tracker.get_growth_rate()
    predicted_load = request_tracker.predict_load()
    request_rate = request_tracker.get_rate()
    
    # Track peak request rate
    new_peak_rate = max(peak_request_rate, request_rate)
    
    # === CAPACITY-BASED SCALING (PRIORITY 1) ===
    # Calculate required pods based on current load
    if metrics["concurrent_requests"] > 0:
        required_pods = int((metrics["concurrent_requests"] * CAPACITY_SAFETY_MARGIN) / REQUESTS_PER_POD_TARGET) + 1
        required_pods = max(MIN_REPLICAS, min(required_pods, MAX_REPLICAS))
    else:
        required_pods = current_replicas
    
    # Force scale-up if severely overloaded
    if can_scale_up and requests_per_pod >= REQUESTS_PER_POD_MAX:
        desired = min(required_pods, MAX_REPLICAS)
        action = "scale_up_capacity"
        reason = f"capacity_overload:{requests_per_pod:.1f}/pod_required:{required_pods}"
        return desired, action, reason, 100, None, new_peak_rate
    
    # === PREDICTIVE SCALING (PRIORITY 2) ===
    # Detect rapid traffic growth and scale proactively
    if can_scale_up and request_growth > RAPID_GROWTH_THRESHOLD:
        # Traffic is growing rapidly, scale proactively
        if current_replicas < required_pods:
            desired = min(current_replicas + 2, required_pods, MAX_REPLICAS)
            action = "scale_up_predictive"
            reason = f"rapid_growth:{request_growth:.1%}_required:{required_pods}"
            return desired, action, reason, 90, None, new_peak_rate
    
    # === HEURISTIC SCORING (PRIORITY 3) ===
    # GPU-AWARE SCORING FOR SHARED ACCELERATOR ARCHITECTURE
    # Weights: 45% queue, 30% GPU, 15% latency, 10% growth
    score = 0
    reasons = []
    
    # 1. Queue/Request Pressure (45 points max) - DOMINANT SIGNAL
    if queue_per_pod >= QUEUE_BACKLOG_THRESHOLD * 2:
        score += 45
        reasons.append(f"queue_critical:{queue_per_pod:.1f}/pod")
    elif queue_per_pod >= QUEUE_BACKLOG_THRESHOLD * 1.5:
        score += 40
        reasons.append(f"queue_very_high:{queue_per_pod:.1f}/pod")
    elif queue_per_pod >= QUEUE_BACKLOG_THRESHOLD:
        score += 35
        reasons.append(f"queue_high:{queue_per_pod:.1f}/pod")
    elif requests_per_pod >= REQUESTS_PER_POD_TARGET * 1.2:
        score += 30
        reasons.append(f"req_high:{requests_per_pod:.1f}/pod")
    elif requests_per_pod >= REQUESTS_PER_POD_TARGET:
        score += 22
        reasons.append(f"req_target:{requests_per_pod:.1f}/pod")
    elif requests_per_pod >= REQUESTS_PER_POD_TARGET * 0.7:
        score += 15
        reasons.append(f"req_moderate:{requests_per_pod:.1f}/pod")
    elif requests_per_pod >= REQUESTS_PER_POD_TARGET * 0.4:
        score += 8
        reasons.append(f"req_low:{requests_per_pod:.1f}/pod")
    
    # 2. GPU Utilization (30 points max) - GPU-AWARE SIGNAL
    if metrics["gpu_avg"] >= 90:
        score += 30
        reasons.append(f"gpu_critical:{metrics['gpu_avg']:.0f}%")
    elif metrics["gpu_avg"] >= 80:
        score += 25
        reasons.append(f"gpu_very_high:{metrics['gpu_avg']:.0f}%")
    elif metrics["gpu_avg"] >= GPU_SCALE_UP_THRESHOLD:
        score += 20
        reasons.append(f"gpu_high:{metrics['gpu_avg']:.0f}%")
    elif metrics["gpu_avg"] >= 50:
        score += 12
        reasons.append(f"gpu_moderate:{metrics['gpu_avg']:.0f}%")
    elif metrics["gpu_avg"] >= 35:
        score += 5
        reasons.append(f"gpu_normal:{metrics['gpu_avg']:.0f}%")
    elif metrics["gpu_avg"] <= GPU_SCALE_DOWN_THRESHOLD:
        score -= 15
        reasons.append(f"gpu_low:{metrics['gpu_avg']:.0f}%")
    
    # 3. Latency Pressure (15 points max)
    if metrics["latency_avg"] >= LATENCY_CRITICAL_MS * 1.5:
        score += 15
        reasons.append(f"lat_critical:{metrics['latency_avg']:.0f}ms")
    elif metrics["latency_avg"] >= LATENCY_CRITICAL_MS:
        score += 12
        reasons.append(f"lat_very_high:{metrics['latency_avg']:.0f}ms")
    elif metrics["latency_avg"] >= LATENCY_SLA_MS * 1.5:
        score += 9
        reasons.append(f"lat_high:{metrics['latency_avg']:.0f}ms")
    elif metrics["latency_avg"] >= LATENCY_SLA_MS:
        score += 6
        reasons.append(f"lat_target:{metrics['latency_avg']:.0f}ms")
    # 4. Request Growth Rate & Predictive Scaling (10 points max)
    if request_growth > 0.6:  # 60% growth
        score += 10
        reasons.append(f"growth_critical:{request_growth:.1%}")
    elif request_growth > 0.4:  # 40% growth
        score += 8
        reasons.append(f"growth_high:{request_growth:.1%}")
    elif request_growth > 0.2:  # 20% growth
        score += 5
        reasons.append(f"growth_moderate:{request_growth:.1%}")
    elif request_growth > 0.05:  # 5% growth
        score += 2
        reasons.append(f"growth_low:{request_growth:.1%}")
    elif request_growth < -0.3:  # Declining
        score -= 8
        reasons.append(f"growth_declining:{request_growth:.1%}")
    
    # Capacity check
    if current_replicas < required_pods:
        score += 10
        reasons.append(f"capacity_needed:{required_pods}")
    
    # === SCALING DECISION ===
    desired = current_replicas
    action = "hold"
    new_low_load_start = low_load_start
    
    # Scale UP conditions
    if can_scale_up and score >= 50:  # Lowered threshold from 55
        # Aggressive scale up based on score
        if score >= 80:
            desired = min(current_replicas + 3, MAX_REPLICAS)
            action = "scale_up_aggressive"
        elif score >= 65:
            desired = min(current_replicas + 2, MAX_REPLICAS)
            action = "scale_up_fast"
        else:
            desired = min(current_replicas + 1, MAX_REPLICAS)
            action = "scale_up"
        new_low_load_start = None  # Reset low load tracking
    
    # Scale DOWN conditions - IMPROVED
    elif can_scale_down and score <= 25 and current_replicas > MIN_REPLICAS:
        # Check if load is truly low
        is_low_load = (
            metrics["concurrent_requests"] <= 3 and 
            metrics["queue_length"] == 0 and
            metrics["gpu_avg"] < GPU_SCALE_DOWN_THRESHOLD and
            request_rate < new_peak_rate * 0.3  # Compare to peak rate
        )
        
        if is_low_load:
            # Track how long we've been in low load state
            if low_load_start is None:
                new_low_load_start = current_time
                reasons.append(f"low_load_detected")
            else:
                low_load_duration = current_time - low_load_start
                if low_load_duration >= LOW_LOAD_DURATION_THRESHOLD:
                    # Scale down after sustained low load
                    desired = max(current_replicas - 1, MIN_REPLICAS)
                    action = "scale_down"
                    reasons.append(f"low_load_{low_load_duration:.0f}s")
                    new_low_load_start = None  # Reset after scaling
                else:
                    reasons.append(f"low_load_wait_{low_load_duration:.0f}s/{LOW_LOAD_DURATION_THRESHOLD}s")
        else:
            new_low_load_start = None  # Reset if load increases
    else:
        # Reset low load tracking if conditions not met
        if score > 25:
            new_low_load_start = None
    
    reason_str = f"score:{score}|" + "|".join(reasons) if reasons else f"score:{score}"
    
    return desired, action, reason_str, score, new_low_load_start, new_peak_rate


def scale(api, replicas):
    body = {"spec": {"replicas": replicas}}
    api.patch_namespaced_deployment_scale(DEPLOYMENT, NAMESPACE, body)


# =============================
# MAIN LOOP
# =============================

def main():
    load_kube_config()
    apps = client.AppsV1Api()
    core = client.CoreV1Api()

    # Initialize trackers
    request_tracker = RequestRateTracker()
    gpu_ema = EWMA(alpha=0.4)
    latency_ema = EWMA(alpha=0.3)
    
    last_scale_up_time = 0
    last_scale_down_time = 0
    low_load_start_time = None  # Track when low load started
    peak_request_rate = 0.0  # Track peak request rate for downscaling
    
    log.info(f"UserScale Improved Scaling Engine Started")
    log.info(f"Features: Capacity-based + Predictive + Heuristic")
    log.info(f"Sync Period: {SYNC_PERIOD}s")
    log.info(f"Replicas: MIN={MIN_REPLICAS} MAX={MAX_REPLICAS}")
    log.info(f"GPU Thresholds: UP={GPU_SCALE_UP_THRESHOLD}% DOWN={GPU_SCALE_DOWN_THRESHOLD}%")
    log.info(f"Latency SLA: {LATENCY_SLA_MS}ms Critical: {LATENCY_CRITICAL_MS}ms")
    log.info(f"Requests per pod: TARGET={REQUESTS_PER_POD_TARGET} MAX={REQUESTS_PER_POD_MAX}")
    log.info(f"Queue backlog threshold: {QUEUE_BACKLOG_THRESHOLD}")
    log.info(f"Low load duration threshold: {LOW_LOAD_DURATION_THRESHOLD}s")

    while True:
        try:
            current_replicas = get_replicas(apps)
            pods = list_pods(core)

            # Fetch metrics
            metrics = fetch_metrics(pods)
            
            # Smooth metrics
            metrics["gpu_avg"] = gpu_ema.update(metrics["gpu_avg"]) or 0
            metrics["latency_avg"] = latency_ema.update(metrics["latency_avg"]) or 0
            
            # Track request rate
            request_tracker.add(metrics["concurrent_requests"])

            # Make scaling decision
            desired, action, reason, score, low_load_start_time, peak_request_rate = decide_scale_heuristic(
                current_replicas,
                metrics,
                request_tracker,
                last_scale_up_time,
                last_scale_down_time,
                low_load_start_time,
                peak_request_rate
            )

            # Execute scaling
            if desired != current_replicas:
                scale(apps, desired)
                if desired > current_replicas:
                    last_scale_up_time = time.time()
                else:
                    last_scale_down_time = time.time()

            if CSV_LOGGING:
                print(f"{time.time()},{current_replicas},{desired},{metrics['gpu_avg']:.1f},"
                      f"{metrics['latency_avg']:.1f},{metrics['concurrent_requests']},{score},{reason}")

            log.info(
                f"ACTION={action} CUR={current_replicas} DES={desired} "
                f"GPU={metrics['gpu_avg']:.1f}% LAT={metrics['latency_avg']:.0f}ms "
                f"REQS={metrics['concurrent_requests']} QUEUE={metrics['queue_length']} "
                f"SCORE={score} REASON={reason}"
            )

        except Exception as e:
            log.exception(f"Loop error: {e}")

        time.sleep(SYNC_PERIOD)


if __name__ == "__main__":
    main()
