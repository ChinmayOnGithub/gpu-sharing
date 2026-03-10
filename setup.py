#!/usr/bin/env python3
"""
Complete Setup Script for UserScale Heuristic Autoscaling Project
Prepares environment, builds images, deploys Kubernetes resources
"""

import subprocess
import time
import sys
import os
import json


def run(cmd, silent=False, timeout=600):
    """Execute shell command"""
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            timeout=timeout,
            capture_output=True,
            text=True
        )
        if not silent:
            if r.stdout.strip():
                print(r.stdout.strip())
            if r.stderr.strip() and "warning" not in r.stderr.lower():
                print(r.stderr.strip())
        return r.returncode == 0
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def header(t):
    print(f"\n{'='*80}\n{t}\n{'='*80}")


def step(msg, ok=True):
    print(f"{'[OK]' if ok else '[FAIL]'} {msg}")


def check_prereq():
    """Check prerequisites"""
    header("Step 1/7: Checking Prerequisites")

    if not run("kubectl version --client", silent=True):
        step("kubectl not found", False)
        sys.exit(1)
    step("kubectl found")

    # Check k8s connectivity
    if not run("kubectl get nodes", silent=True):
        step("Cannot connect to Kubernetes cluster", False)
        print("\n  Fix: Ensure k3s is running")
        print("  sudo systemctl status k3s")
        sys.exit(1)
    step("Kubernetes cluster accessible")

    if not run("docker --version", silent=True):
        step("Docker not installed", False)
        sys.exit(1)
    step("Docker found")

    if not run("docker ps", silent=True):
        step("Docker daemon not running", False)
        sys.exit(1)
    step("Docker daemon running")

    # Check GPU
    if run("nvidia-smi", silent=True):
        step("GPU detected")
    else:
        step("No GPU detected (workload will use CPU)", False)


def verify_image():
    """Verify Docker image exists"""
    header("Step 2/7: Verifying Docker Image")
    
    result = subprocess.run(
        "docker images userscale-gpu:latest --format '{{.Repository}}'",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if "userscale-gpu" in result.stdout:
        step("Docker image 'userscale-gpu:latest' found")
        return True
    else:
        step("Docker image 'userscale-gpu:latest' not found", False)
        print("\n  Build the image first:")
        print("  docker build -f Dockerfile.gpu -t userscale-gpu:latest .")
        return False


def verify_k3s_image():
    """Verify image is loaded in k3s"""
    header("Step 3/7: Verifying k3s Image")
    
    result = subprocess.run(
        "sudo k3s crictl images | grep userscale-gpu",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if "userscale-gpu" in result.stdout:
        step("Image loaded in k3s")
        return True
    else:
        step("Image not loaded in k3s", False)
        print("\n  The image must be imported into k3s containerd")
        print("  This was done manually as per environment update")
        return False


def cleanup_namespace():
    """Clean up existing namespace"""
    header("Step 4/7: Cleaning Up Namespace")
    
    result = subprocess.run(
        "kubectl get namespace userscale 2>&1",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if "NotFound" not in result.stderr and "not found" not in result.stdout.lower():
        step("Namespace exists, cleaning up...")
        
        # Scale deployments to 0
        run("kubectl scale deployment --all -n userscale --replicas=0", silent=True)
        time.sleep(3)
        
        # Delete resources
        run("kubectl delete hpa --all -n userscale --ignore-not-found=true", silent=True)
        run("kubectl delete deployment --all -n userscale --ignore-not-found=true", silent=True)
        run("kubectl delete service --all -n userscale --ignore-not-found=true", silent=True)
        
        # Force delete namespace
        run("kubectl patch namespace userscale -p '{\"metadata\":{\"finalizers\":[]}}' --type=merge", silent=True)
        run("kubectl delete namespace userscale --force --grace-period=0", silent=True)
        
        # Wait for deletion
        for i in range(20):
            result = subprocess.run(
                "kubectl get namespace userscale 2>&1",
                shell=True,
                capture_output=True,
                text=True
            )
            if "NotFound" in result.stderr or "not found" in result.stdout.lower():
                break
            time.sleep(1)
        
        step("Namespace cleaned")
    else:
        step("No existing namespace")
    
    # Create namespace
    run("kubectl create namespace userscale")
    step("Fresh namespace created")


def deploy_manifests():
    """Deploy Kubernetes manifests"""
    header("Step 5/7: Deploying Manifests")

    for m in ["k8s/userscale-gpu.yaml", "k8s/hpa-gpu.yaml"]:
        if not os.path.exists(m):
            step(f"Missing manifest: {m}", False)
            sys.exit(1)
        step(f"Applying {m}")
        run(f"kubectl apply -f {m}")
    
    time.sleep(5)
    step("Manifests applied")


def wait_ready():
    """Wait for deployments to be ready"""
    header("Step 6/7: Waiting for Deployments")

    apps = ["userscale-app", "userscale-scaler", "hpa-app"]

    for app in apps:
        step(f"Waiting for {app}...")
        result = subprocess.run(
            f"kubectl wait --for=condition=available --timeout=120s deployment/{app} -n userscale 2>&1",
            shell=True,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            step(f"{app} ready")
        else:
            step(f"{app} not ready (timeout)", False)

    time.sleep(5)
    print("\nCurrent pods:")
    run("kubectl get pods -n userscale -o wide")


def setup_port_forwarding():
    """Setup port forwarding"""
    header("Step 7/7: Setting Up Port Forwarding")
    
    # Kill existing
    run("pkill -f 'kubectl port-forward'", silent=True)
    time.sleep(2)
    
    # Start new
    subprocess.Popen(
        "kubectl port-forward -n userscale svc/hpa-app 8002:8000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)
    
    subprocess.Popen(
        "kubectl port-forward -n userscale svc/userscale-app 8001:8000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    
    step("Port forwarding started")
    print("  HPA:       http://localhost:8002")
    print("  UserScale: http://localhost:8001")


def main():
    print("\n" + "="*80)
    print("  USERSCALE HEURISTIC AUTOSCALING - SETUP")
    print("="*80 + "\n")
    
    check_prereq()
    
    if not verify_image():
        sys.exit(1)
    
    if not verify_k3s_image():
        sys.exit(1)
    
    cleanup_namespace()
    deploy_manifests()
    wait_ready()
    setup_port_forwarding()

    print("\n" + "="*80)
    print("  SETUP COMPLETE!")
    print("="*80 + "\n")
    print("Next steps:")
    print("  python3 run_files/demo.py")
    print("  python3 run_files/watch_pods.py  (in another terminal)")
    print("")


if __name__ == "__main__":
    main()
