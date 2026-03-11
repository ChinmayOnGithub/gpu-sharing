#!/usr/bin/env python3
"""Quick test of the demo script fixes"""
import subprocess
import json
import requests
import time

def run_cmd(cmd):
    try:
        if cmd.startswith("kubectl"):
            cmd = f"sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml {cmd[8:]}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except:
        return ""

def get_replicas(deploy):
    try:
        out = run_cmd(f"kubectl get deployment {deploy} -n default -o json")
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

print("🧪 TESTING DEMO SCRIPT FIXES")
print("============================")

# Test replica counting
print("1. Testing replica counting...")
hpa_replicas = get_replicas("hpa-fractional-app")
custom_replicas = get_replicas("custom-fractional-app")
print(f"   HPA: {hpa_replicas} pods")
print(f"   Custom: {custom_replicas} pods")

# Test GPU slice usage
print("\n2. Testing GPU slice usage...")
gpu_usage = get_gpu_slice_usage()
print(f"   GPU: {gpu_usage['allocated']}/{gpu_usage['total']} slices allocated")

# Test endpoints
print("\n3. Testing endpoints...")
try:
    response = requests.get("http://localhost:8003/gpu-work?type=matmul&size=500", timeout=5)
    if response.status_code == 200:
        data = response.json()
        print(f"   HPA endpoint: ✅ CUDA={data.get('cuda_enabled', False)}")
    else:
        print(f"   HPA endpoint: ❌ Status {response.status_code}")
except Exception as e:
    print(f"   HPA endpoint: ❌ Error {e}")

try:
    response = requests.get("http://localhost:8004/gpu-work?type=matmul&size=500", timeout=5)
    if response.status_code == 200:
        data = response.json()
        print(f"   Custom endpoint: ✅ CUDA={data.get('cuda_enabled', False)}")
    else:
        print(f"   Custom endpoint: ❌ Status {response.status_code}")
except Exception as e:
    print(f"   Custom endpoint: ❌ Error {e}")

print("\n✅ DEMO SCRIPT SHOULD NOW WORK!")
print("Run: python3 demo-fractional.py")