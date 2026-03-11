#!/bin/bash
# Run this ONCE on the Ubuntu host as root/sudo
# Enables CUDA MPS so each pod gets enforced 1/6th GPU compute
set -e

echo "=== Setting up CUDA MPS for GPU fractional sharing ==="

# Step 1: Switch GPU to EXCLUSIVE_PROCESS mode (required for MPS)
sudo nvidia-smi -i 0 -c EXCLUSIVE_PROCESS
echo "✅ GPU set to EXCLUSIVE_PROCESS mode"

# Step 2: Start MPS daemon
sudo nvidia-cuda-mps-control -d
echo "✅ MPS daemon started"

# Step 3: Verify MPS is running
sleep 2
if pgrep -f "nvidia-cuda-mps" > /dev/null; then
    echo "✅ MPS control daemon is running"
else
    echo "❌ MPS daemon failed to start"
    exit 1
fi

# Step 4: Check MPS server status
echo "start_server -uid 0" | sudo nvidia-cuda-mps-control
echo "✅ MPS server started"

# Step 5: Create MPS socket directory
sudo mkdir -p /tmp/nvidia-mps
sudo chmod 755 /tmp/nvidia-mps

# Step 6: Verify
nvidia-smi -i 0 -q | grep "Compute Mode"
echo ""
echo "=== MPS Setup Complete ==="
echo "Now rebuild & redeploy your device plugin with the updated Allocate() code"