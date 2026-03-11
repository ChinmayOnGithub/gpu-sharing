#!/usr/bin/env python3
import subprocess
import json

def run_cmd(cmd):
    try:
        if cmd.startswith("kubectl"):
            cmd = f"sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml {cmd[8:]}"  # Remove 'kubectl ' and add the fixed pattern
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except Exception as e:
        print(f"Error: {e}")
        return ""

def get_replicas(deploy):
    try:
        out = run_cmd(f"kubectl get deployment {deploy} -n default -o json")
        if not out:
            print(f"No output for deployment {deploy}")
            return 0
        data = json.loads(out)
        ready = data["status"].get("readyReplicas", 0)
        print(f"Deployment {deploy}: {ready} ready replicas")
        return ready
    except Exception as e:
        print(f"Error getting replicas for {deploy}: {e}")
        return 0

print("Testing replica counting...")
hpa_replicas = get_replicas("hpa-fractional-app")
custom_replicas = get_replicas("custom-fractional-app")

print(f"\nResults:")
print(f"HPA: {hpa_replicas} pods")
print(f"Custom: {custom_replicas} pods")