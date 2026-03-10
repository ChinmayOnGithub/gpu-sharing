# Fractional GPU Allocation System - Project Structure

## 📁 Clean Project Structure

```
fractional-gpu-system/
├── 🔧 Core Components
│   ├── device-plugin/              # Go-based Kubernetes device plugin
│   │   ├── main.go                 # Device plugin entry point
│   │   ├── server.go               # gRPC server implementation
│   │   ├── Dockerfile              # Device plugin container
│   │   └── go.mod/go.sum          # Go dependencies
│   │
│   ├── gpu-manager/               # Python-based GPU slice manager
│   │   ├── gpu_manager_fixed.py   # Flask API for slice management
│   │   └── Dockerfile             # GPU manager container
│   │
│   └── k8s/                       # Kubernetes configurations
│       ├── gpu-sidecar-daemonset-fixed.yaml  # Main DaemonSet
│       ├── hpa-fractional-gpu.yaml           # HPA application
│       ├── custom-fractional-scaler.yaml     # Custom scaler
│       ├── gpu-app-image/         # GPU workload application
│       │   ├── gpu_app.py         # Flask app with GPU simulation
│       │   └── Dockerfile         # Application container
│       ├── custom-scaler-image/   # Custom autoscaler
│       │   ├── gpu_scaler.py      # GPU-aware scaling logic
│       │   └── Dockerfile         # Scaler container
│       └── README.md              # K8s components documentation
│
├── 🚀 Deployment & Testing
│   ├── build-and-deploy-all.sh    # Complete system deployment
│   ├── rebuild-and-test.sh        # Rebuild with improvements
│   ├── fix-demo-and-deploy.sh     # Fix and redeploy script
│   ├── check-status.sh            # System health check
│   └── demo-fractional.py         # Performance comparison demo
│
├── 📚 Documentation
│   ├── README.md                  # Main project documentation
│   ├── README-FRACTIONAL-GPU.md   # Detailed technical guide
│   ├── FRACTIONAL_GPU_EXPLANATION.md  # System explanation
│   ├── PROJECT_STRUCTURE.md       # This file
│   └── SAFETY.md                  # Safety guidelines
│
├── 📊 Results & Data
│   ├── results/                   # Demo experiment results
│   ├── baseline.csv              # Performance baselines
│   └── experiment_results.csv    # Historical results
│
└── ⚙️ Configuration
    ├── .config/hardware_config.json  # Hardware specifications
    ├── requirements.txt           # Python dependencies
    └── setup.py                  # Package setup
```

## 🎯 Essential Files Only

### Core System (Must Have)
- `device-plugin/` - Kubernetes device plugin for GPU slice advertisement
- `gpu-manager/` - GPU slice allocation management API
- `k8s/gpu-sidecar-daemonset-fixed.yaml` - Main DaemonSet deployment
- `k8s/hpa-fractional-gpu.yaml` - HPA-based autoscaling demo
- `k8s/custom-fractional-scaler.yaml` - Custom GPU-aware autoscaling

### Deployment (Essential)
- `build-and-deploy-all.sh` - One-command system deployment
- `check-status.sh` - System health verification
- `demo-fractional.py` - Performance comparison demonstration

### Documentation (Important)
- `README.md` - Project overview and quick start
- `FRACTIONAL_GPU_EXPLANATION.md` - Technical explanation
- `k8s/README.md` - Kubernetes components guide

## 🗑️ Cleaned Up (Removed)

### Removed Files
- 20+ old deployment scripts (consolidated into `build-and-deploy-all.sh`)
- 15+ individual test pod YAML files (replaced by applications)
- 10+ fix/debug scripts (functionality moved to main scripts)
- Old demo scripts (replaced by `demo-fractional.py`)
- Duplicate configurations and outdated experiments

### Benefits of Cleanup
- ✅ **Simplified structure** - Easy to understand and navigate
- ✅ **Clear purpose** - Each file has a specific, documented role
- ✅ **Reduced confusion** - No duplicate or conflicting configurations
- ✅ **Better maintenance** - Fewer files to manage and update
- ✅ **Professional presentation** - Clean, organized project structure

## 🚀 Quick Start (After Cleanup)

1. **Deploy the system**:
   ```bash
   bash build-and-deploy-all.sh
   ```

2. **Check system status**:
   ```bash
   bash check-status.sh
   ```

3. **Run the demo**:
   ```bash
   python3 demo-fractional.py
   ```

4. **Read the explanation**:
   ```bash
   cat FRACTIONAL_GPU_EXPLANATION.md
   ```

The project is now clean, organized, and ready for presentation!