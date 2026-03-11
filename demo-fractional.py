#!/usr/bin/env python3
"""
Fractional GPU Autoscaling Demo - HPA vs Custom Scaler
"""

import requests
import time
import threading
import subprocess
import json
import os
from datetime import datetime

NAMESPACE = "default"
HPA_DEPLOY = "hpa-fractional-app"
CUSTOM_DEPLOY = "custom-fractional-app"

HPA_URL = "http://localhost:8003"
CUSTOM_URL = "http://localhost:8004"

TEST_DURATION = 120
WORKERS = 15

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULTS_DIR = f"results/fractional_{TIMESTAMP}"
os.makedirs(RESULTS_DIR, exist_ok=True)

def run_cmd(cmd):
    try:
        if cmd.startswith("kubectl"):
            cmd = f"sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml {cmd[8:]}"  # Remove 'kubectl ' and add the fixed pattern
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except:
        return ""

def get_replicas(deploy):
    try:
        out = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
        data = json.loads(out)
        return data["status"].get("readyReplicas", 0)
    except:
        return 0

def get_gpu_slice_usage():
    try:
        pod_out = run_cmd("kubectl get pods -o json")
        if not pod_out:
            return {"allocated": 0, "total": 6, "available": 6}
        
        pods_data = json.loads(pod_out)
        allocated_slices = 0
        
        for pod in pods_data.get("items", []):
            if pod.get("status", {}).get("phase") == "Running":
                for container in pod.get("spec", {}).get("containers", []):
                    resources = container.get("resources", {}).get("requests", {})
                    if "example.com/gpu-slice" in resources:
                        allocated_slices += int(resources["example.com/gpu-slice"])
        
        available_slices = 6 - allocated_slices
        return {"allocated": allocated_slices, "total": 6, "available": available_slices}
    except:
        return {"allocated": 0, "total": 6, "available": 6}

def generate_load(url, stop_event, stats):
    while not stop_event.is_set():
        try:
            t0 = time.time()
            response = requests.get(f"{url}/gpu-work?type=matmul&size=1000", timeout=30)
            latency = (time.time() - t0) * 1000
            
            if response.status_code == 200:
                stats["requests"] += 1
                stats["latencies"].append(latency)
            else:
                stats["failures"] += 1
        except:
            stats["failures"] += 1
            time.sleep(0.5)

def monitor_scaling(deploy, stop_event, timeline):
    while not stop_event.is_set():
        replicas = get_replicas(deploy)
        gpu_usage = get_gpu_slice_usage()
        
        timeline.append({
            "time": time.time(),
            "replicas": replicas,
            "gpu_allocated": gpu_usage["allocated"],
            "gpu_available": gpu_usage["available"]
        })
        time.sleep(2)

def run_experiment(name, deploy, url):
    print(f"\n{'='*60}")
    print(f"  {name} EXPERIMENT - {TEST_DURATION} SECONDS")
    print(f"{'='*60}\n")
    
    stats = {"requests": 0, "failures": 0, "latencies": []}
    timeline = []
    stop_event = threading.Event()
    
    # Start monitoring
    monitor_thread = threading.Thread(target=monitor_scaling, args=(deploy, stop_event, timeline))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Start load generators
    load_threads = []
    for _ in range(WORKERS):
        t = threading.Thread(target=generate_load, args=(url, stop_event, stats))
        t.daemon = True
        t.start()
        load_threads.append(t)
    
    # Run experiment
    start_time = time.time()
    while time.time() - start_time < TEST_DURATION:
        elapsed = int(time.time() - start_time)
        current_replicas = get_replicas(deploy)
        gpu_usage = get_gpu_slice_usage()
        
        print(f"\rTIME: {elapsed:3d}s/{TEST_DURATION}s | Pods: {current_replicas} | GPU: {gpu_usage['allocated']}/{gpu_usage['total']} | Requests: {stats['requests']} | Failures: {stats['failures']}", end="", flush=True)
        time.sleep(1)
    
    print()
    stop_event.set()
    time.sleep(3)
    
    # Calculate results
    if timeline:
        replicas_list = [t["replicas"] for t in timeline]
        gpu_list = [t["gpu_allocated"] for t in timeline]
        
        results = {
            "experiment": name,
            "duration_seconds": TEST_DURATION,
            "min_pods": min(replicas_list) if replicas_list else 0,
            "max_pods": max(replicas_list) if replicas_list else 0,
            "avg_pods": sum(replicas_list) / len(replicas_list) if replicas_list else 0,
            "max_gpu_usage": max(gpu_list) if gpu_list else 0,
            "total_requests": stats["requests"],
            "failed_requests": stats["failures"],
            "success_rate": (stats["requests"] / (stats["requests"] + stats["failures"]) * 100) if (stats["requests"] + stats["failures"]) > 0 else 0,
            "throughput_rps": stats["requests"] / TEST_DURATION,
            "avg_latency_ms": sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0,
            "scaling_events": len([i for i in range(1, len(replicas_list)) if replicas_list[i] != replicas_list[i-1]]),
        }
    else:
        results = {"error": "No monitoring data collected"}
    
    # Save results
    with open(f"{RESULTS_DIR}/{name.lower().replace(' ', '_')}_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Print summary
    print(f"\n{name} RESULTS:")
    print(f"  Max Pods: {results.get('max_pods', 0)}")
    print(f"  Max GPU Usage: {results.get('max_gpu_usage', 0)}/6")
    print(f"  Throughput: {results.get('throughput_rps', 0):.1f} req/s")
    print(f"  Success Rate: {results.get('success_rate', 0):.1f}%")
    print(f"  Scaling Events: {results.get('scaling_events', 0)}")
    
    return results

def main():
    print("\n" + "="*60)
    print("  FRACTIONAL GPU AUTOSCALING COMPARISON")
    print("  HPA vs Custom Fractional GPU Scaler")
    print("="*60 + "\n")
    
    print("🎯 System Features:")
    print("✅ GPU slice allocation (1GB per slice)")
    print("✅ Memory-based spatial partitioning")
    print("✅ HPA: CPU-based scaling")
    print("✅ Custom: GPU-aware intelligent scaling")
    print("")
    
    input("Press Enter to start experiments...")
    
    # Experiment 1: HPA
    print("\n" + "="*40)
    print("  PREPARING HPA EXPERIMENT")
    print("="*40)
    
    hpa_results = run_experiment("HPA Fractional GPU", HPA_DEPLOY, HPA_URL)
    
    # ── Restart GPU manager to clear stuck slice allocations ──
    print("\n🔄 Restarting GPU manager to clear allocations...")
    subprocess.run(
        "sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml rollout restart daemonset gpu-sidecar -n kube-system",
        shell=True
    )
    
    # Wait for it to come back 2/2
    for _ in range(20):
        ready = subprocess.run(
            "sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml get pods -n kube-system "
            "-l app=gpu-sidecar --no-headers | awk '{print $2}'",
            shell=True, capture_output=True, text=True
        ).stdout.strip()
        if ready == "2/2":
            print("✅ GPU manager ready - all slices free")
            break
        print(".", end="", flush=True)
        time.sleep(3)
    
    print("\nWaiting 30 seconds between experiments...")
    time.sleep(30)
    
    # Experiment 2: Custom Scaler
    print("\n" + "="*40)
    print("  PREPARING CUSTOM SCALER EXPERIMENT")
    print("="*40)
    
    custom_results = run_experiment("Custom Fractional GPU", CUSTOM_DEPLOY, CUSTOM_URL)
    
    # Comparison
    print(f"\n{'='*60}")
    print(f"  FINAL COMPARISON")
    print(f"{'='*60}\n")
    
    print(f"{'Metric':<25} {'HPA':<15} {'Custom':<15} {'Winner':<10}")
    print("-" * 65)
    
    metrics = [
        ("Max Pods", "max_pods"),
        ("Max GPU Usage", "max_gpu_usage"),
        ("Throughput (req/s)", "throughput_rps"),
        ("Success Rate %", "success_rate"),
        ("Scaling Events", "scaling_events")
    ]
    
    custom_wins = 0
    hpa_wins = 0
    
    for label, key in metrics:
        hpa_val = hpa_results.get(key, 0)
        custom_val = custom_results.get(key, 0)
        
        if key == "scaling_events":  # Lower is better
            winner = "HPA" if hpa_val < custom_val else "Custom" if custom_val < hpa_val else "Tie"
        else:  # Higher is better
            winner = "HPA" if hpa_val > custom_val else "Custom" if custom_val > hpa_val else "Tie"
        
        if winner == "Custom": custom_wins += 1
        elif winner == "HPA": hpa_wins += 1
        
        print(f"{label:<25} {hpa_val:<15.2f} {custom_val:<15.2f} {winner:<10}")
    
    # Save comparison
    comparison = {
        "hpa_results": hpa_results,
        "custom_results": custom_results,
        "winner": "Custom" if custom_wins > hpa_wins else "HPA" if hpa_wins > custom_wins else "Tie",
        "timestamp": datetime.now().isoformat()
    }
    
    with open(f"{RESULTS_DIR}/comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)
    
    print("\n" + "="*60)
    print("🏆 EXPERIMENT COMPLETE!")
    print("="*60)
    
    overall_winner = comparison["winner"]
    if overall_winner == "Custom":
        print("🎯 CUSTOM GPU SCALER WINS!")
        print("• Superior GPU-aware autoscaling")
        print("• Intelligent resource management")
        print("• Better performance metrics")
    elif overall_winner == "HPA":
        print("🎯 HPA WINS!")
        print("• Effective CPU-based scaling")
    else:
        print("🎯 TIE!")
        print("• Both scalers performed similarly")
    
    print(f"\n✅ Fractional GPU allocation demonstrated successfully!")
    print(f"📊 Results saved to {RESULTS_DIR}/")
    print("="*60)

if __name__ == "__main__":
    main()