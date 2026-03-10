#!/bin/bash

echo "Building GPU Slice Device Plugin..."
go mod tidy
go build -o gpu-slice-plugin .

if [ $? -eq 0 ]; then
    echo "Build successful! Binary: gpu-slice-plugin"
    echo "To run: sudo ./gpu-slice-plugin"
else
    echo "Build failed!"
    exit 1
fi