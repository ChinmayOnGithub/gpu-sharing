#!/usr/bin/env python3
import time
import requests
import json
from kubernetes import client, config
import os

# Load Kubernetes config
config.load_incluster_config()
apps_v1 = client.AppsV1Api()
core_v1 = client.CoreV1Api()

NAMESPACE = "default"
DEPLOYMENT = "custom-fractional-app"
MIN_REPLICAS = 1
MAX_REPLICAS = 6  # Max 6 because we have 6 GPU slices

def get_deployment_replicas():
    try:
        deployment = apps_v1.read_namespaced_deployment(DEPLOYMENT, NAMESPACE)
        return deployment.status.ready_replicas or 0
    except:
        return 0

def scale_deployment(replicas):
    try:
        # Get current deployment
        deployment = apps_v1.read_namespaced_deployment(DEPLOYMENT, NAMESPACE)
        
        # Update replicas
        deployment.spec.replicas = replicas
        
        # Apply update
        apps_v1.patch_namespaced_deployment(
            name=DEPLOYMENT,
            namespace=NAMESPACE,
            body=deployment
        )
        print(f"Scaled {DEPLOYMENT} to {replicas} replicas")
        return True
    except Exception as e:
        print(f"Failed to scale: {e}")
        return False

def get_pod_metrics():
    try:
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE,
            label_selector=f"app=custom-fractional-app"
        )
        
        total_gpu_util = 0
        total_cpu_util = 0
        active_pods = 0
        total_requests = 0
        
        for pod in pods.items:
            if pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            
            try:
                response = requests.get(
                    f"http://{pod.status.pod_ip}:8080/metrics",
                    timeout=3
                )
                if response.status_code == 200:
                    metrics = response.json()
                    total_gpu_util += metrics.get("gpu_utilization", 0)
                    total_cpu_util += metrics.get("cpu_percent", 0)
                    total_requests += metrics.get("request_count", 0)
                    active_pods += 1
            except:
                pass
        
        if active_pods > 0:
            return {
                "avg_gpu_util": total_gpu_util / active_pods,
                "avg_cpu_util": total_cpu_util / active_pods,
                "total_requests": total_requests,
                "active_pods": active_pods
            }
        return {"avg_gpu_util": 0, "avg_cpu_util": 0, "total_requests": 0, "active_pods": 0}
    except Exception as e:
        print(f"Error getting metrics: {e}")
        return {"avg_gpu_util": 0, "avg_cpu_util": 0, "total_requests": 0, "active_pods": 0}

def get_gpu_slice_usage():
    """Check actual GPU slice usage from pods"""
    try:
        pods = core_v1.list_pod_for_all_namespaces()
        used_slices = 0
        
        for pod in pods.items:
            if pod.status.phase == "Running":
                # Check if pod has GPU slice resource
                for container in pod.spec.containers:
                    if container.resources and container.resources.requests:
                        gpu_slices = container.resources.requests.get("example.com/gpu-slice")
                        if gpu_slices:
                            try:
                                used_slices += int(gpu_slices)
                            except (ValueError, TypeError):
                                pass
        
        return {"allocated": used_slices, "total": 6, "available": 6 - used_slices}
    except Exception as e:
        print(f"Error getting GPU slice usage: {e}")
        return {"allocated": 0, "total": 6, "available": 6}

def main():
    print("Custom GPU Scaler started")
    print(f"Target: {DEPLOYMENT} in {NAMESPACE}")
    print(f"Replica range: {MIN_REPLICAS}-{MAX_REPLICAS}")
    
    while True:
        try:
            current_replicas = get_deployment_replicas()
            metrics = get_pod_metrics()
            gpu_slice_usage = get_gpu_slice_usage()
            
            print(f"Current: {current_replicas} pods, GPU: {metrics['avg_gpu_util']:.1f}%, CPU: {metrics['avg_cpu_util']:.1f}%, GPU Slices: {gpu_slice_usage['allocated']}/{gpu_slice_usage['total']}")
            
            # GPU-AWARE SCALING LOGIC
            target_replicas = current_replicas
            scale_reason = ""
            
            # 1. Scale up if GPU utilization is high AND we have available slices
            if (metrics['avg_gpu_util'] > 30 or metrics['total_requests'] > 50) and current_replicas < MAX_REPLICAS and gpu_slice_usage['available'] > 0:
                target_replicas = min(current_replicas + 1, MAX_REPLICAS)
                scale_reason = f"High GPU load (GPU: {metrics['avg_gpu_util']:.1f}%, Requests: {metrics['total_requests']})"
            
            # 2. Aggressive scale up if very high utilization
            elif metrics['avg_gpu_util'] > 60 and current_replicas < MAX_REPLICAS and gpu_slice_usage['available'] > 0:
                target_replicas = min(current_replicas + 2, MAX_REPLICAS)
                scale_reason = f"Very high GPU utilization ({metrics['avg_gpu_util']:.1f}%)"
            
            # 3. Scale down if GPU utilization is very low
            elif metrics['avg_gpu_util'] < 15 and metrics['total_requests'] < 10 and current_replicas > MIN_REPLICAS:
                target_replicas = max(current_replicas - 1, MIN_REPLICAS)
                scale_reason = f"Low GPU activity (GPU: {metrics['avg_gpu_util']:.1f}%, Requests: {metrics['total_requests']})"
            
            if target_replicas != current_replicas:
                print(f"🎯 SCALING: {current_replicas} → {target_replicas} pods ({scale_reason})")
                scale_deployment(target_replicas)
            else:
                print(f"✅ STABLE: {current_replicas} pods (GPU: {metrics['avg_gpu_util']:.1f}%)")
            
        except Exception as e:
            print(f"Scaler error: {e}")
        
        time.sleep(10)  # Check every 10 seconds

if __name__ == "__main__":
    main()