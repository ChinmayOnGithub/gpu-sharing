#!/usr/bin/env python3
"""
Clean Fractional GPU Demo - No spam output
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

TEST_DURATION = 60  # Shorter test
WORKERS = 10        # Fewer workers

def run_cmd_quiet(cmd):
    """Run command quietly without output spam"""
    try:
        if cmd.startswith("kubectl"):
            cmd = f"sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml {cmd[8:]}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except:
        return ""

def get_replicas(deploy):
    try:
        out = run_cmd_quiet(f"kubectl get deployment {deploy} -o jsonpath='{{.status.readyReplicas}}'")
        return int(out) if out.isdigit() else 0
    except:
        return 0

def get_gpu_slice_usage():
    try:
        # Simple approach - count running pods with GPU slice requests
        out = run_cmd_quiet("kubectl get pods -o json")
        if not out:
            return {"allocated": 0, "total": 6, "available": 6}
        
        pods_data = json.loads(out)
        allocated_slices = 0
        
        for pod in pods_data.get("items", []):
            if pod.get("status", {}).get("phase") == "Running":
                for container in pod.get("spec", {}).get("containers", []):
                    resources = container.get("resources", {}).get("requests", {})
                    if "example.com/gpu-slice" in resources:
                        allocated_slices += int(resources["example.com/gpu-slice"])
        
        return {"allocated": allocated_slices, "total": 6, "available": 6 - allocated_slices}
    except:
        return {"allocated": 0, "total": 6, "available": 6}

def test_connectivity():
    """Test if apps are accessible"""
    print("🔍 Testing connectivity...")
    
    try:
        resp = requests.get(f"{HPA_URL}/health", timeout=3)
        if resp.status_code == 200:
            print("✅ HPA app accessible")
        else:
            print("❌ HPA app not responding")
            return False
    except:
        print("❌ HPA app not accessible")
        return False
    
    try:
        resp = requests.get(f"{CUSTOM_URL}/health", timeout=3)
        if resp.status_code == 200:
            print("✅ Custom app accessible")
        else:
            print("❌ Custom app not responding")
            return False
    except:
        print("❌ Custom app not accessible")
        return False
    
    return True

def generate_load_worker(url, stop_event, stats):
    """Single worker thread for load generation"""
    while not stop_event.is_set():
        try:
            start_time = time.time()
            response = requests.get(f"{url}/gpu-work?type=matmul&size=800", timeout=10)
            latency = (time.time() - start_time) * 1000
            
            with threading.Lock():
                if response.status_code == 200:
                    stats["requests"] += 1
                    stats["total_latency"] += latency
                else:
                    stats["failures"] += 1
        except:
            with threading.Lock():
                stats["failures"] += 1
        
        time.sleep(0.1)  # Small delay between requests

def run_load_test(name, deploy, url):
    print(f"\n{'='*50}")
    print(f"🧪 {name} TEST ({TEST_DURATION}s)")
    print(f"{'='*50}")
    
    if not test_connectivity():
        print("❌ Connectivity test failed - skipping")
        return None
    
    # Initialize stats
    stats = {"requests": 0, "failures": 0, "total_latency": 0}
    stop_event = threading.Event()
    
    # Start load generation threads
    threads = []
    for i in range(WORKERS):
        t = threading.Thread(target=generate_load_worker, args=(url, stop_event, stats))
        t.daemon = True
        t.start()
        threads.append(t)
    
    print(f"🔥 Started {WORKERS} workers generating load...")
    
    # Monitor for test duration
    start_time = time.time()
    last_update = 0
    
    while time.time() - start_time < TEST_DURATION:
        elapsed = int(time.time() - start_time)
        
        # Update every 5 seconds
        if elapsed - last_update >= 5:
            current_replicas = get_replicas(deploy)
            gpu_usage = get_gpu_slice_usage()
            
            print(f"⏱️  {elapsed:2d}s | Pods: {current_replicas} | "
                  f"GPU: {gpu_usage['allocated']}/{gpu_usage['total']} | "
                  f"Requests: {stats['requests']} | Failures: {stats['failures']}")
            
            last_update = elapsed
        
        time.sleep(1)
    
    # Stop load generation
    stop_event.set()
    for t in threads:
        t.join(timeout=2)
    
    # Calculate results
    total_requests = stats["requests"] + stats["failures"]
    success_rate = (stats["requests"] / total_requests * 100) if total_requests > 0 else 0
    avg_latency = (stats["total_latency"] / stats["requests"]) if stats["requests"] > 0 else 0
    throughput = stats["requests"] / TEST_DURATION
    
    final_replicas = get_replicas(deploy)
    final_gpu = get_gpu_slice_usage()
    
    results = {
        "test": name,
        "duration": TEST_DURATION,
        "final_replicas": final_replicas,
        "max_gpu_usage": final_gpu["allocated"],
        "total_requests": stats["requests"],
        "failed_requests": stats["failures"],
        "success_rate": success_rate,
        "avg_latency_ms": avg_latency,
        "throughput_rps": throughput
    }
    
    print(f"\n📊 {name} RESULTS:")
    print(f"   Final Pods: {final_replicas}")
    print(f"   GPU Usage: {final_gpu['allocated']}/6 slices")
    print(f"   Requests: {stats['requests']} ({success_rate:.1f}% success)")
    print(f"   Throughput: {throughput:.1f} req/s")
    print(f"   Avg Latency: {avg_latency:.1f}ms")
    
    return results

def main():
    print("🚀 FRACTIONAL GPU SCALING TEST")
    print("==============================")
    
    # Test HPA
    hpa_results = run_load_test("HPA", HPA_DEPLOY, HPA_URL)
    
    if hpa_results:
        print("\n⏳ Waiting 30s between tests...")
        time.sleep(30)
        
        # Test Custom Scaler
        custom_results = run_load_test("CUSTOM SCALER", CUSTOM_DEPLOY, CUSTOM_URL)
        
        if custom_results:
            print(f"\n{'='*50}")
            print("🏆 COMPARISON")
            print(f"{'='*50}")
            print(f"{'Metric':<20} {'HPA':<12} {'Custom':<12}")
            print("-" * 44)
            print(f"{'Final Pods':<20} {hpa_results['final_replicas']:<12} {custom_results['final_replicas']:<12}")
            print(f"{'Max GPU Usage':<20} {hpa_results['max_gpu_usage']:<12} {custom_results['max_gpu_usage']:<12}")
            print(f"{'Throughput (rps)':<20} {hpa_results['throughput_rps']:<12.1f} {custom_results['throughput_rps']:<12.1f}")
            print(f"{'Success Rate %':<20} {hpa_results['success_rate']:<12.1f} {custom_results['success_rate']:<12.1f}")
    
    print("\n✅ Test complete!")

if __name__ == "__main__":
    main()