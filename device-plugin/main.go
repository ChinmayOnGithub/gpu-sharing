package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

func main() {
	log.Println("Starting GPU Slice Device Plugin")

	// Create device plugin
	devicePlugin := NewGPUSliceDevicePlugin()

	// Start the device plugin server
	if err := devicePlugin.Start(); err != nil {
		log.Fatalf("Could not start device plugin: %v", err)
	}
	log.Println("Device plugin server started")

	// Register with kubelet
	if err := devicePlugin.Register(pluginapi.KubeletSocket, resourceName); err != nil {
		log.Fatalf("Could not register device plugin: %v", err)
	}
	log.Printf("Device plugin registered with resource name: %s", resourceName)

	// Set up signal handling for graceful shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	// Wait for shutdown signal
	<-sigCh
	log.Println("Received shutdown signal")

	// Stop the device plugin
	if err := devicePlugin.Stop(); err != nil {
		log.Printf("Error stopping device plugin: %v", err)
	}
	log.Println("Device plugin stopped")
}