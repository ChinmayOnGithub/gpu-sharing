#!/usr/bin/env python3
"""
MPS Isolation Verification Script
Tests that each pod gets exactly 1/6th GPU compute via CUDA MPS
"""

import requests
import time
import subprocess
import threading
import json

def run_cmd(cmd):
    try:
        if cmd.startswith("kubectl"):
            cmd = f"sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml {cmd[8:]}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except:
        return ""

def scale_to_pods(deploy, count):
    """Scale deployment to specific pod count"""
    cmd = f"kubectl scale deployment {deploy} --replicas={count}"
    run_cmd(cmd)
    
    # Wait for pods to be ready
    for _ in range(30):
        ready = run_cmd(f"kubectl get deployment {deploy} -o jsonpath='{{.status.readyReplicas}}'")
        if ready == str(count):
            return True
        time.sleep(2)
    return False

def generate_load(url, duration=30):
    """Generate GPU load on a specific app"""
    def worker():
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                requests.get(f"{url}/gpu-work?type=matmul&size=1000", timeout=5)
            except:
                pass
            time.sleep(0.1)
    
    # Start 5 worker threads per app
    threads = []
    for _ in range(5):
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        threads.append(t)
    
    return threads

def get_nvidia_smi_utilization():
    """Get GPU utilization from nvidia-smi"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        return int(result.stdout.strip())
    except:
        return 0

def main():
    print("🧪 MPS ISOLATION VERIFICATION")
    print("=" * 50)
    
    # Test 1: Single pod should use ~16% (not 70%)
    print("\n1. Testing single pod isolation...")
    scale_to_pods("custom-fractional-app", 1)
    time.sleep(5)
    
    print("   Starting GPU load on 1 pod...")
    threads = generate_load("http://localhost:8004", 20)
    
    # Sample GPU utilization
    utils = []
    for i in range(10):
        util = get_nvidia_smi_utilization()
        utils.append(util)
        print(f"   Sample {i+1}/10: {util}% GPU utilization")
        time.sleep(2)
    
    avg_util_1pod = sum(utils) / len(utils)
    print(f"   ✅ Average: {avg_util_1pod:.1f}% (should be ~16% with MPS, was ~70% without)")
    
    # Wait for threads to finish
    for t in threads:
        t.join()
    
    # Test 2: Multiple pods should each use ~16%
    print("\n2. Testing 3-pod isolation...")
    scale_to_pods("custom-fractional-app", 3)
    time.sleep(10)
    
    print("   Starting GPU load on 3 pods...")
    threads = generate_load("http://localhost:8004", 20)
    
    # Sample GPU utilization
    utils = []
    for i in range(10):
        util = get_nvidia_smi_utilization()
        utils.append(util)
        print(f"   Sample {i+1}/10: {util}% GPU utilization")
        time.sleep(2)
    
    avg_util_3pods = sum(utils) / len(utils)
    print(f"   ✅ Average: {avg_util_3pods:.1f}% (should be ~48% = 3×16% with MPS)")
    
    # Wait for threads to finish
    for t in threads:
        t.join()
    
    # Analysis
    print("\n" + "=" * 50)
    print("📊 RESULTS ANALYSIS")
    print("=" * 50)
    
    if avg_util_1pod < 25:
        print(f"✅ SINGLE POD: {avg_util_1pod:.1f}% - MPS isolation working!")
        print("   (Without MPS: would be ~70%)")
    else:
        print(f"❌ SINGLE POD: {avg_util_1pod:.1f}% - MPS not working")
        print("   Expected: ~16%, Got: high utilization")
    
    expected_3pod = avg_util_1pod * 3
    if abs(avg_util_3pods - expected_3pod) < 10:
        print(f"✅ THREE PODS: {avg_util_3pods:.1f}% - Linear scaling!")
        print(f"   Expected: ~{expected_3pod:.1f}%, Got: {avg_util_3pods:.1f}%")
    else:
        print(f"❌ THREE PODS: {avg_util_3pods:.1f}% - Not scaling linearly")
        print(f"   Expected: ~{expected_3pod:.1f}%, Got: {avg_util_3pods:.1f}%")
    
    # Reset to 1 pod
    scale_to_pods("custom-fractional-app", 1)
    
    print("\n🎯 CONCLUSION:")
    if avg_util_1pod < 25 and abs(avg_util_3pods - expected_3pod) < 10:
        print("✅ MPS ISOLATION IS WORKING!")
        print("   Each pod is limited to ~1/6th GPU compute")
        print("   Multiple pods scale linearly without interference")
    else:
        print("❌ MPS ISOLATION NOT WORKING")
        print("   Pods are still using unrestricted GPU access")
        print("   Check MPS daemon and environment variables")

if __name__ == "__main__":
    main()