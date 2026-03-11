#!/usr/bin/env python3
"""
Test current fractional GPU system
"""
import requests
import time

def test_apps():
    print("🧪 Testing current fractional GPU system...")
    
    # Test HPA app
    try:
        resp = requests.get("http://localhost:8003/health", timeout=5)
        if resp.status_code == 200:
            print("✅ HPA app accessible")
            data = resp.json()
            print(f"   Pod: {data.get('pod', 'unknown')}")
            print(f"   GPU Slice: {data.get('gpu_slice', 'unknown')}")
        else:
            print("❌ HPA app not responding")
    except Exception as e:
        print(f"❌ HPA app error: {e}")
    
    # Test Custom app
    try:
        resp = requests.get("http://localhost:8004/health", timeout=5)
        if resp.status_code == 200:
            print("✅ Custom app accessible")
            data = resp.json()
            print(f"   Pod: {data.get('pod', 'unknown')}")
            print(f"   GPU Slice: {data.get('gpu_slice', 'unknown')}")
        else:
            print("❌ Custom app not responding")
    except Exception as e:
        print(f"❌ Custom app error: {e}")
    
    # Test GPU work
    print("\n🔥 Testing GPU workload...")
    try:
        start = time.time()
        resp = requests.get("http://localhost:8004/gpu-work?type=matmul&size=1000", timeout=30)
        duration = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ GPU work completed in {duration:.2f}s")
            print(f"   Duration: {data.get('duration_ms', 0):.1f}ms")
            print(f"   CUDA: {data.get('cuda_enabled', False)}")
        else:
            print(f"❌ GPU work failed: {resp.status_code}")
    except Exception as e:
        print(f"❌ GPU work error: {e}")
    
    # Test metrics
    print("\n📊 Testing metrics...")
    try:
        resp = requests.get("http://localhost:8004/metrics", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Metrics available:")
            print(f"   Requests: {data.get('request_count', 0)}")
            print(f"   GPU Util: {data.get('gpu_utilization', 0):.1f}%")
            print(f"   Concurrent: {data.get('concurrent_requests', 0)}")
            print(f"   Queue: {data.get('queue_length', 0)}")
        else:
            print(f"❌ Metrics failed: {resp.status_code}")
    except Exception as e:
        print(f"❌ Metrics error: {e}")

if __name__ == "__main__":
    test_apps()