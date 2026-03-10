# GPU Slice Device Plugin

A minimal Kubernetes device plugin that advertises GPU slices.

## Features

- Advertises 6 GPU slices: `slice0` through `slice5`
- Resource name: `example.com/gpu-slice`
- Maps `/dev/nvidia0` to containers
- Implements full Kubernetes device plugin API

## Build

```bash
chmod +x build.sh
./build.sh
```

Or manually:
```bash
go mod tidy
go build -o gpu-slice-plugin .
```

## Run

The plugin must run as root to access device plugin socket:

```bash
sudo ./gpu-slice-plugin
```

## Usage in Pods

Request GPU slices in your pod spec:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-slice-test
spec:
  containers:
  - name: test
    image: nvidia/cuda:11.0-base
    resources:
      limits:
        example.com/gpu-slice: 2
```

## Implementation Notes

- All slices are marked as `Healthy`
- `Allocate` returns dummy device mapping for `/dev/nvidia0`
- No actual GPU logic implemented yet - this is just the framework
- Health checks can be disabled with `DP_DISABLE_HEALTHCHECKS=1`