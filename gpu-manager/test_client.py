#!/usr/bin/env python3
"""
Test client for GPU Manager API
"""

import json
import requests
import time


class GPUManagerClient:
    def __init__(self, base_url="http://localhost:5000"):
        self.base_url = base_url
    
    def allocate(self, pod_name: str, slices: int = 1):
        """Allocate GPU slices"""
        response = requests.post(f"{self.base_url}/allocate", 
                               json={"pod_name": pod_name, "slices": slices})
        return response.json()
    
    def release(self, pod_name: str):
        """Release GPU slices"""
        response = requests.post(f"{self.base_url}/release", 
                               json={"pod_name": pod_name})
        return response.json()
    
    def status(self):
        """Get status"""
        response = requests.get(f"{self.base_url}/status")
        return response.json()
    
    def health(self):
        """Health check"""
        response = requests.get(f"{self.base_url}/health")
        return response.json()


def test_gpu_manager():
    """Test the GPU manager functionality"""
    client = GPUManagerClient()
    
    print("=== GPU Manager Test ===")
    
    # Health check
    print("\n1. Health Check:")
    try:
        health = client.health()
        print(f"✓ Health: {health}")
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return
    
    # Get initial status
    print("\n2. Initial Status:")
    status = client.status()
    print(f"GPU Info: {status['gpu_info']}")
    print(f"Total Slices: {status['total_slices']}")
    print(f"Allocated Slices: {status['allocated_slices']}")
    
    # Test allocation
    print("\n3. Testing Allocation:")
    result = client.allocate("test-pod-1", 2)
    print(f"Allocate 2 slices to test-pod-1: {result}")
    
    result = client.allocate("test-pod-2", 1)
    print(f"Allocate 1 slice to test-pod-2: {result}")
    
    # Check status after allocation
    print("\n4. Status After Allocation:")
    status = client.status()
    print(f"Allocated Slices: {status['allocated_slices']}")
    for slice_id, info in status['allocation_table'].items():
        if info['allocated']:
            print(f"  {slice_id}: {info['pod_name']} ({info['memory_limit_gb']}GB)")
    
    # Test over-allocation
    print("\n5. Testing Over-allocation:")
    result = client.allocate("test-pod-3", 5)  # Should fail
    print(f"Allocate 5 slices (should fail): {result}")
    
    # Test release
    print("\n6. Testing Release:")
    result = client.release("test-pod-1")
    print(f"Release test-pod-1: {result}")
    
    # Final status
    print("\n7. Final Status:")
    status = client.status()
    print(f"Allocated Slices: {status['allocated_slices']}")
    print(f"Active Processes: {len(status['active_processes'])}")
    
    # Cleanup
    print("\n8. Cleanup:")
    client.release("test-pod-2")
    print("Released remaining allocations")


if __name__ == '__main__':
    test_gpu_manager()