#!/usr/bin/env python3
"""
Automated GPU Autoscaling Experiments - GPU AS SHARED ACCELERATOR

EXPERIMENT OBJECTIVE:
Compare HPA (CPU-triggered) vs UserScale (GPU-aware) on single-GPU architecture.

ARCHITECTURE:
- Single physical GPU shared across all pods via time-slicing
- GPU is NOT a scalable resource (more pods ≠ more GPU capacity)
- Focus: GPU efficiency and intelligent scheduling, not raw compute scaling

EVALUATION METRICS:
- GPU utilization efficiency (how well GPU is used)
- Requests handled per pod (efficiency per replica)
- Scaling responsiveness (how quickly system adapts)
- Latency stability under load
- Resource efficiency (fewer pods for same performance)

SCALER COMPARISON:
- HPA: Naive GPU usage (no batching, individual requests, CPU-triggered)
- UserScale: Optimized GPU usage (batching enabled, GPU-aware scheduling)

BENCHMARK STRUCTURE:
- Warmup: 60s with 3 workers
- Benchmark: 420s (7 minutes) with dynamic load pattern
- Load pattern: 5 → 70 → 30 → 60 → 5 workers (tests scale-up and scale-down)
"""

import requests
import time
import threading
import subprocess
import json
import os
from datetime import datetime

NAMESPACE = "userscale"
HPA_DEPLOY = "hpa-app"
USERSCALE_DEPLOY = "userscale-app"

HPA_URL = "http://localhost:8002"
USERSCALE_URL = "http://localhost:8001"

PORT = 8000
WARMUP_DURATION = 60       # 60 seconds warmup
TEST_DURATION = 420        # 420 seconds benchmark (7 minutes)
WORKLOAD_SIZE = 1000       # Matrix size (optimized for GPU as shared accelerator)

# DYNAMIC LOAD PATTERN - GPU AS SHARED ACCELERATOR
WARMUP_WORKERS = 3         # Very low load during warmup
LOAD_PATTERN = [
    (0, 60, 5),            # 0-60s: Low load (5 workers)
    (60, 180, 70),         # 60-180s: Heavy load (70 workers) - scale up
    (180, 300, 30),        # 180-300s: Medium load (30 workers) - scale down
    (300, 360, 60),        # 300-360s: Heavy load again (60 workers) - scale up
    (360, 420, 5),         # 360-420s: Low load (5 workers) - scale down
]

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_cmd(cmd):
    """Execute command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except:
        return ""


def get_replicas(deploy):
    """Get current replica count"""
    try:
        out = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
        data = json.loads(out)
        return data["status"].get("readyReplicas", 0)
    except:
        return 0


def get_pod_metrics(selector):
    """Get aggregated metrics from all pods"""
    try:
        out = run_cmd(f"kubectl get pods -n {NAMESPACE} -l {selector} -o json")
        pods = json.loads(out)["items"]
        
        gpu_vals = []
        cpu_vals = []
        latencies = []
        total_requests = 0
        
        for pod in pods:
            ip = pod["status"].get("podIP")
            if not ip:
                continue
            try:
                m = requests.get(f"http://{ip}:{PORT}/metrics", timeout=2).json()
                if m.get("gpu_utilization", 0) > 0:
                    gpu_vals.append(m["gpu_utilization"])
                cpu_vals.append(m.get("cpu_percent", 0))
                if m.get("avg_latency_ms", 0) > 0:
                    latencies.append(m["avg_latency_ms"])
                total_requests += m.get("request_count", 0)
            except:
                pass
        
        return {
            "gpu_avg": sum(gpu_vals) / len(gpu_vals) if gpu_vals else 0,
            "gpu_max": max(gpu_vals) if gpu_vals else 0,
            "cpu_avg": sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0,
            "latency_avg": sum(latencies) / len(latencies) if latencies else 0,
            "latency_max": max(latencies) if latencies else 0,
            "total_requests": total_requests
        }
    except:
        return {"gpu_avg": 0, "gpu_max": 0, "cpu_avg": 0, "latency_avg": 0, "latency_max": 0, "total_requests": 0}


def generate_load(url, stop_event, stats, active_workers_control):
    """Generate load on the service with dynamic worker control"""
    while not stop_event.is_set():
        # Check if this worker should be active
        if not active_workers_control.get("active", True):
            time.sleep(0.5)
            continue
            
        try:
            t0 = time.time()
            r = requests.get(f"{url}/compute?size={WORKLOAD_SIZE}", timeout=120)
            latency = (time.time() - t0) * 1000
            
            if r.status_code == 200:
                with threading.Lock():
                    stats["requests"] += 1
                    stats["latencies"].append(latency)
            else:
                with threading.Lock():
                    stats["failures"] += 1
        except Exception as e:
            with threading.Lock():
                stats["failures"] += 1
            time.sleep(0.5)


def monitor_scaling(deploy, selector, stop_event, timeline, warmup_complete=None):
    """Monitor pod scaling over time"""
    while not stop_event.is_set():
        replicas = get_replicas(deploy)
        metrics = get_pod_metrics(selector)
        
        is_benchmark = warmup_complete.is_set() if warmup_complete else True
        
        timeline.append({
            "time": time.time(),
            "replicas": replicas,
            "gpu_avg": metrics["gpu_avg"],
            "gpu_max": metrics["gpu_max"],
            "cpu_avg": metrics["cpu_avg"],
            "latency_avg": metrics["latency_avg"],
            "latency_max": metrics["latency_max"],
            "total_requests": metrics["total_requests"],
            "benchmark": is_benchmark  # Mark if this is benchmark phase
        })
        
        time.sleep(3)


def scale_to_zero(deploy):
    """Scale deployment to 0"""
    run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas=0")
    time.sleep(5)


def scale_to_one(deploy):
    """Scale deployment to 1"""
    run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas=1")
    time.sleep(10)


def run_experiment(name, url, deploy, selector):
    """Run a single experiment with warmup and dynamic load pattern"""
    print(f"\n{'='*80}")
    print(f"  {name} EXPERIMENT")
    print(f"  Warmup: {WARMUP_DURATION}s ({WARMUP_WORKERS} workers)")
    print(f"  Benchmark: {TEST_DURATION}s (dynamic load pattern)")
    print(f"{'='*80}\n")
    
    print("Load Pattern:")
    for start, end, workers in LOAD_PATTERN:
        print(f"  {start}-{end}s: {workers} workers")
    print()
    
    stats = {"requests": 0, "failures": 0, "latencies": []}
    timeline = []
    stop_event = threading.Event()
    warmup_complete = threading.Event()
    
    # Start monitoring
    monitor_thread = threading.Thread(target=monitor_scaling, args=(deploy, selector, stop_event, timeline, warmup_complete))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Create worker pool with control mechanism
    max_workers = max(w for _, _, w in LOAD_PATTERN)
    worker_controls = []
    load_threads = []
    
    for i in range(max_workers):
        control = {"active": False}
        worker_controls.append(control)
        t = threading.Thread(target=generate_load, args=(url, stop_event, stats, control))
        t.daemon = True
        t.start()
        load_threads.append(t)
    
    def set_active_workers(count):
        """Activate/deactivate workers to match desired count"""
        for i in range(len(worker_controls)):
            worker_controls[i]["active"] = (i < count)
    
    # === WARMUP PHASE ===
    print(f"WARMUP PHASE ({WARMUP_DURATION}s with {WARMUP_WORKERS} workers)...")
    set_active_workers(WARMUP_WORKERS)
    
    start_time = time.time()
    while time.time() - start_time < WARMUP_DURATION:
        elapsed = int(time.time() - start_time)
        current_replicas = get_replicas(deploy)
        print(f"\r[WARMUP] {elapsed}s/{WARMUP_DURATION}s | Pods: {current_replicas} | Requests: {stats['requests']}", end="", flush=True)
        time.sleep(1)
    
    print("\n\nWARMUP COMPLETE - Starting benchmark with dynamic load...\n")
    warmup_complete.set()
    
    # Reset stats for benchmark
    warmup_requests = stats["requests"]
    stats["requests"] = 0
    stats["failures"] = 0
    stats["latencies"] = []
    
    # === BENCHMARK PHASE WITH DYNAMIC LOAD ===
    print(f"BENCHMARK PHASE ({TEST_DURATION}s with dynamic load)...")
    benchmark_start = time.time()
    current_phase = 0
    
    while time.time() - benchmark_start < TEST_DURATION:
        elapsed = time.time() - benchmark_start
        elapsed_int = int(elapsed)
        
        # Determine current load phase
        for i, (start, end, workers) in enumerate(LOAD_PATTERN):
            if start <= elapsed < end:
                if i != current_phase:
                    current_phase = i
                    set_active_workers(workers)
                    print(f"\n[LOAD CHANGE] Switching to {workers} workers")
                current_workers = workers
                break
        
        current_replicas = get_replicas(deploy)
        print(f"\r[BENCHMARK] {elapsed_int}s/{TEST_DURATION}s | Workers: {current_workers} | Pods: {current_replicas} | Requests: {stats['requests']} | Failures: {stats['failures']}", end="", flush=True)
        time.sleep(1)
    
    print()
    
    # Stop all threads
    stop_event.set()
    time.sleep(2)
    
    # Calculate statistics (only from benchmark phase)
    if timeline:
        # Filter timeline to only benchmark phase
        benchmark_timeline = [t for t in timeline if t.get("benchmark", False)]
        
        if benchmark_timeline:
            replicas_list = [t["replicas"] for t in benchmark_timeline]
            gpu_avgs = [t["gpu_avg"] for t in benchmark_timeline if t["gpu_avg"] > 0]
            gpu_maxs = [t["gpu_max"] for t in benchmark_timeline if t["gpu_max"] > 0]
            cpu_avgs = [t["cpu_avg"] for t in benchmark_timeline]
            
            if not stats["latencies"] and benchmark_timeline:
                timeline_latencies = [t["latency_avg"] for t in benchmark_timeline if t["latency_avg"] > 0]
                if timeline_latencies:
                    stats["latencies"] = timeline_latencies
            
            cpu_per_pod_list = []
            for t in benchmark_timeline:
                if t["replicas"] > 0:
                    cpu_per_pod_list.append(t["cpu_avg"] / t["replicas"])
            
            avg_pods = sum(replicas_list) / len(replicas_list) if replicas_list else 0
            throughput_rps = stats["requests"] / TEST_DURATION
            requests_per_pod = stats["requests"] / max(avg_pods, 1)
            gpu_efficiency = (sum(gpu_avgs) / len(gpu_avgs) if gpu_avgs else 0) / max(avg_pods, 1)
            scaling_efficiency = avg_pods / max(max(replicas_list) if replicas_list else 1, 1)
            
            sorted_latencies = sorted(stats["latencies"]) if stats["latencies"] else [0]
            p95_idx = int(len(sorted_latencies) * 0.95)
            p99_idx = int(len(sorted_latencies) * 0.99)
            
            results = {
                "experiment": name,
                "warmup_duration_s": WARMUP_DURATION,
                "warmup_workers": WARMUP_WORKERS,
                "benchmark_duration_s": TEST_DURATION,
                "load_pattern": LOAD_PATTERN,
                "warmup_requests": warmup_requests,
                "workload_size": WORKLOAD_SIZE,
                "min_pods": min(replicas_list) if replicas_list else 0,
                "max_pods": max(replicas_list) if replicas_list else 0,
                "avg_pods": avg_pods,
                "gpu_utilization_avg": sum(gpu_avgs) / len(gpu_avgs) if gpu_avgs else 0,
                "gpu_utilization_max": max(gpu_maxs) if gpu_maxs else 0,
                "cpu_utilization_avg": sum(cpu_avgs) / len(cpu_avgs) if cpu_avgs else 0,
                "cpu_per_pod_avg": sum(cpu_per_pod_list) / len(cpu_per_pod_list) if cpu_per_pod_list else 0,
                "latency_avg_ms": sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0,
                "latency_min_ms": min(stats["latencies"]) if stats["latencies"] else 0,
                "latency_max_ms": max(stats["latencies"]) if stats["latencies"] else 0,
                "latency_p95_ms": sorted_latencies[p95_idx] if sorted_latencies else 0,
                "latency_p99_ms": sorted_latencies[p99_idx] if sorted_latencies else 0,
                "total_requests": stats["requests"],
                "failed_requests": stats["failures"],
                "success_rate": (stats["requests"] / (stats["requests"] + stats["failures"]) * 100) if (stats["requests"] + stats["failures"]) > 0 else 0,
                "throughput_rps": throughput_rps,
                "requests_per_pod": requests_per_pod,
                "gpu_efficiency": gpu_efficiency,
                "scaling_efficiency": scaling_efficiency,
                "scaling_events": len([i for i in range(1, len(replicas_list)) if replicas_list[i] != replicas_list[i-1]]),
                "timeline": benchmark_timeline
            }
        else:
            results = {"error": "No benchmark data collected"}
    else:
        results = {"error": "No data collected"}
    
    # Save results
    with open(f"{RESULTS_DIR}/{name.lower().replace(' ', '_')}_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Print summary
    print(f"\n{name} RESULTS:")
    print(f"  Warmup Requests: {warmup_requests}")
    print(f"  Benchmark Requests: {results.get('total_requests', 0)}")
    print(f"  Throughput: {results.get('throughput_rps', 0):.2f} req/s")
    print(f"  Avg Response Time: {results.get('latency_avg_ms', 0):.1f}ms")
    print(f"  Max Response Time: {results.get('latency_max_ms', 0):.1f}ms")
    print(f"  GPU Utilization: avg={results.get('gpu_utilization_avg', 0):.1f}% max={results.get('gpu_utilization_max', 0):.1f}%")
    print(f"  Pods: min={results.get('min_pods', 0)} max={results.get('max_pods', 0)} avg={results.get('avg_pods', 0):.1f}")
    print(f"  Scaling Events: {results.get('scaling_events', 0)}")
    print(f"  Success Rate: {results.get('success_rate', 0):.1f}%")
    
    return results


def print_comparison(hpa_results, userscale_results):
    """Print comparison between HPA and UserScale - GPU as Shared Accelerator"""
    print(f"\n{'='*90}")
    print(f"  FINAL COMPARISON - HPA vs UserScale")
    print(f"  GPU AS SHARED ACCELERATOR ARCHITECTURE")
    print(f"{'='*90}\n")
    
    def winner(hpa_val, us_val, lower_is_better=False):
        if abs(hpa_val - us_val) < 0.01:
            return "TIE"
        if lower_is_better:
            return "HPA" if hpa_val < us_val else "UserScale"
        else:
            return "HPA" if hpa_val > us_val else "UserScale"
    
    print(f"{'Metric':<40} {'HPA':<20} {'UserScale':<20} {'Winner':<10}")
    print(f"{'-'*90}")
    
    # PRIMARY METRICS - FOCUS ON GPU EFFICIENCY
    metrics = [
        ("GPU Utilization Avg (%)", "gpu_utilization_avg", False),
        ("Requests Per Pod", "requests_per_pod", False),
        ("Throughput (req/s)", "throughput_rps", False),
        ("Avg Response Time (ms)", "latency_avg_ms", True),
        ("P95 Response Time (ms)", "latency_p95_ms", True),
        ("Total Requests", "total_requests", False),
        ("Success Rate (%)", "success_rate", False),
        ("Avg Pods", "avg_pods", True),
        ("Scaling Events", "scaling_events", False),
        ("GPU Efficiency", "gpu_efficiency", False),
    ]
    
    wins = {"HPA": 0, "UserScale": 0, "TIE": 0}
    
    for label, key, lower_better in metrics:
        hpa_val = hpa_results.get(key, 0)
        us_val = userscale_results.get(key, 0)
        w = winner(hpa_val, us_val, lower_better)
        wins[w] += 1
        
        print(f"{label:<40} {hpa_val:<20.2f} {us_val:<20.2f} {w:<10}")
    
    print("\n" + "="*90)
    print("  OVERALL WINNER")
    print("="*90 + "\n")
    
    print(f"HPA Wins:       {wins['HPA']}")
    print(f"UserScale Wins: {wins['UserScale']}")
    print(f"Ties:           {wins['TIE']}")
    
    if wins['UserScale'] > wins['HPA']:
        improvement = ((wins['UserScale'] - wins['HPA']) / len(metrics)) * 100
        print(f"\nWINNER: UserScale ({improvement:.0f}% superiority)")
    elif wins['HPA'] > wins['UserScale']:
        print(f"\nWINNER: HPA")
    else:
        print(f"\nRESULT: Tie")
    
    # Save comparison
    comparison = {
        "hpa": hpa_results,
        "userscale": userscale_results,
        "wins": wins,
        "timestamp": datetime.now().isoformat()
    }
    
    with open(f"{RESULTS_DIR}/comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)
    
    print(f"\nResults saved to {RESULTS_DIR}/")


def ensure_deployment_scaled(deploy, replicas=1):
    """
    Ensure deployment is scaled to desired replicas
    """
    try:
        result = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
        if result:
            dep = json.loads(result)
            current_replicas = dep.get("spec", {}).get("replicas", 0)
            
            if current_replicas != replicas:
                print(f"Scaling {deploy} from {current_replicas} to {replicas} replicas...")
                run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas={replicas}")
                time.sleep(5)
                return True
            return True
    except:
        return False


def ensure_port_forward(service, local_port):
    """
    Ensure port forwarding is active, restart if needed
    """
    # Check if port is already in use
    try:
        result = subprocess.run(
            f"lsof -ti:{local_port}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Port is in use, check if it's our port-forward
            pid = result.stdout.strip()
            if pid:
                # Kill existing process
                subprocess.run(f"kill {pid}", shell=True, timeout=5)
                time.sleep(2)
    except:
        pass
    
    # Start port forwarding in background
    try:
        subprocess.Popen(
            f"kubectl port-forward -n {NAMESPACE} svc/{service} {local_port}:8000",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(3)
        return True
    except:
        return False


def check_service_ready(name, url, deploy, max_retries=20):
    """
    Robust service readiness check with automatic fixes
    """
    print(f"Checking {name} service...")
    
    # First, ensure deployment is scaled up
    ensure_deployment_scaled(deploy, replicas=1)
    
    # Ensure port forwarding is active
    local_port = 8002 if "hpa" in deploy else 8001
    ensure_port_forward(deploy, local_port)
    
    for attempt in range(max_retries):
        try:
            # Try HTTP health check first
            response = requests.get(f"{url}/healthz", timeout=3)
            if response.status_code == 200:
                print(f"{name} service ready (HTTP check passed)")
                return True
        except:
            pass
        
        # Fallback: Check pod status via kubectl
        try:
            result = run_cmd(f"kubectl get pods -n {NAMESPACE} -l app={deploy},scaler={'hpa' if 'hpa' in deploy else 'userscale'} -o json")
            if result:
                pods = json.loads(result)
                items = pods.get("items", [])
                
                if not items:
                    # No pods found, ensure deployment is scaled
                    if attempt == 5:
                        print(f"WARNING: No pods found, rescaling {deploy}...")
                        ensure_deployment_scaled(deploy, replicas=1)
                    continue
                
                # Check if any pod is running and ready
                for pod in items:
                    status = pod.get("status", {})
                    phase = status.get("phase", "")
                    conditions = status.get("conditions", [])
                    
                    # Check if pod is Running
                    if phase == "Running":
                        # Check if pod is Ready
                        for condition in conditions:
                            if condition.get("type") == "Ready" and condition.get("status") == "True":
                                print(f"{name} service ready (pod running and ready)")
                                # Give it a moment to fully initialize
                                time.sleep(2)
                                return True
                    
                    # Check for CrashLoopBackOff or other issues
                    container_statuses = status.get("containerStatuses", [])
                    for cs in container_statuses:
                        state = cs.get("state", {})
                        if "waiting" in state:
                            reason = state["waiting"].get("reason", "")
                            if "CrashLoopBackOff" in reason or "Error" in reason:
                                print(f"ERROR: {name} pod in {reason} state")
                                print(f"   Checking logs...")
                                run_cmd(f"kubectl logs -n {NAMESPACE} -l app={deploy} --tail=20")
                                return False
        except Exception as e:
            pass
        
        # Wait before retry
        if attempt < max_retries - 1:
            print(f"⏳ {name} not ready yet, waiting... (attempt {attempt + 1}/{max_retries})")
            time.sleep(3)
    
    print(f"ERROR: {name} service not ready after {max_retries} attempts")
    print(f"   Checking deployment status...")
    run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE}")
    run_cmd(f"kubectl get pods -n {NAMESPACE} -l app={deploy}")
    return False


def preflight_check():
    """
    Pre-flight checks and automatic setup
    """
    print("\nPRE-FLIGHT CHECKS\n")
    
    # Check namespace exists
    result = run_cmd("kubectl get namespace userscale 2>&1")
    if "NotFound" in result or "not found" in result.lower():
        print("ERROR: Namespace 'userscale' not found")
        print("   Run: python3 run_files/setup.py")
        return False
    print("Namespace exists")
    
    # Check deployments exist
    result = run_cmd(f"kubectl get deployment {HPA_DEPLOY} -n {NAMESPACE} 2>&1")
    if "NotFound" in result or "not found" in result.lower():
        print(f"ERROR: Deployment '{HPA_DEPLOY}' not found")
        print("   Run: kubectl apply -f k8s/hpa-gpu.yaml")
        return False
    print(f"{HPA_DEPLOY} deployment exists")
    
    result = run_cmd(f"kubectl get deployment {USERSCALE_DEPLOY} -n {NAMESPACE} 2>&1")
    if "NotFound" in result or "not found" in result.lower():
        print(f"ERROR: Deployment '{USERSCALE_DEPLOY}' not found")
        print("   Run: kubectl apply -f k8s/userscale-gpu.yaml")
        return False
    print(f"{USERSCALE_DEPLOY} deployment exists")
    
    # Kill any existing port forwards
    print("🔄 Cleaning up old port forwards...")
    subprocess.run("pkill -f 'kubectl port-forward'", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(2)
    
    return True


def main():
    print("\n" + "="*80)
    print("  GPU AS SHARED ACCELERATOR - AUTOSCALING EXPERIMENTS")
    print("  HPA vs UserScale - GPU Efficiency Comparison")
    print("="*80 + "\n")
    
    # Display architecture information
    print(f"ARCHITECTURE:")
    print(f"   Single GPU shared across all pods via time-slicing")
    print(f"   Focus: GPU efficiency and intelligent scheduling")
    print(f"   HPA: Naive GPU usage (no batching)")
    print(f"   UserScale: Optimized GPU usage (batching enabled)")
    print()
    
    # Display workload information
    print(f"WORKLOAD CONFIGURATION:")
    print(f"   Type: Matrix Multiplication (GPU workload)")
    print(f"   Size: {WORKLOAD_SIZE}×{WORKLOAD_SIZE} matrices")
    print(f"   Warmup: {WARMUP_DURATION}s with {WARMUP_WORKERS} workers")
    print(f"   Benchmark: {TEST_DURATION}s with dynamic load pattern")
    print(f"\nDYNAMIC LOAD PATTERN:")
    for start, end, workers in LOAD_PATTERN:
        print(f"   {start}-{end}s: {workers} workers")
    print()
    
    # Pre-flight checks
    if not preflight_check():
        return
    
    # Robust service readiness checks with automatic fixes
    hpa_ready = check_service_ready("HPA", HPA_URL, HPA_DEPLOY)
    userscale_ready = check_service_ready("UserScale", USERSCALE_URL, USERSCALE_DEPLOY)
    
    if not hpa_ready or not userscale_ready:
        print("\nERROR: Services not ready after automatic fixes.")
        print("\nTROUBLESHOOTING:")
        print("   1. Check deployments:")
        print("      kubectl get deployments -n userscale")
        print("   2. Check pods:")
        print("      kubectl get pods -n userscale")
        print("   3. Check pod logs:")
        print(f"      kubectl logs -n userscale -l app={HPA_DEPLOY if not hpa_ready else USERSCALE_DEPLOY}")
        print("   4. Manual port forward:")
        print("      kubectl port-forward -n userscale svc/hpa-app 8002:8000 &")
        print("      kubectl port-forward -n userscale svc/userscale-app 8001:8000 &")
        return
    
    print("\nAll services ready!\n")
    input("Press Enter to start experiments...\n")
    
    # Experiment 1: HPA
    scale_to_one(HPA_DEPLOY)
    hpa_results = run_experiment(
        "HPA",
        HPA_URL,
        HPA_DEPLOY,
        "app=hpa-app,scaler=hpa"
    )
    scale_to_zero(HPA_DEPLOY)
    
    print("\nWaiting 30 seconds before next experiment...")
    time.sleep(30)
    
    # Experiment 2: UserScale
    scale_to_one(USERSCALE_DEPLOY)
    userscale_results = run_experiment(
        "UserScale",
        USERSCALE_URL,
        USERSCALE_DEPLOY,
        "app=userscale-app,scaler=userscale"
    )
    scale_to_zero(USERSCALE_DEPLOY)
    
    # Print comparison
    print_comparison(hpa_results, userscale_results)
    
    print("\nExperiments complete!")
    print(f"Results saved to {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
