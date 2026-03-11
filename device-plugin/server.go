package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path"
	"time"

	"google.golang.org/grpc"
	pluginapi "k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1"
)

const (
	resourceName   = "example.com/gpu-slice"
	serverSock     = pluginapi.DevicePluginPath + "gpu-slice.sock"
	envDisableHealthChecks = "DP_DISABLE_HEALTHCHECKS"
)

// GPUSliceDevicePlugin implements the Kubernetes device plugin API
type GPUSliceDevicePlugin struct {
	socket string
	server *grpc.Server
	health chan *pluginapi.Device
	stop   chan interface{}
}

// NewGPUSliceDevicePlugin returns an initialized GPUSliceDevicePlugin
func NewGPUSliceDevicePlugin() *GPUSliceDevicePlugin {
	return &GPUSliceDevicePlugin{
		socket: serverSock,
		health: make(chan *pluginapi.Device),
		stop:   make(chan interface{}),
	}
}

// GetDevicePluginOptions returns the values of the optional settings for this plugin
func (m *GPUSliceDevicePlugin) GetDevicePluginOptions(context.Context, *pluginapi.Empty) (*pluginapi.DevicePluginOptions, error) {
	return &pluginapi.DevicePluginOptions{}, nil
}

// ListAndWatch returns a stream of List of Devices
// Whenever a Device state change or a Device disappears, ListAndWatch
// returns the new list
func (m *GPUSliceDevicePlugin) ListAndWatch(e *pluginapi.Empty, s pluginapi.DevicePlugin_ListAndWatchServer) error {
	log.Println("ListAndWatch called")
	
	// Create 6 GPU slices - each represents 1GB of GPU memory
	devices := make([]*pluginapi.Device, 6)
	for i := 0; i < 6; i++ {
		devices[i] = &pluginapi.Device{
			ID:     fmt.Sprintf("slice%d", i),
			Health: pluginapi.Healthy,
		}
	}

	s.Send(&pluginapi.ListAndWatchResponse{Devices: devices})

	for {
		select {
		case <-m.stop:
			return nil
		case d := <-m.health:
			// Health update
			d.Health = pluginapi.Healthy
			s.Send(&pluginapi.ListAndWatchResponse{Devices: devices})
		}
	}
}

// Allocate is called during container creation so that the Device
// Plugin can run device specific operations and instruct Kubelet
// of the steps to make the Device available in the container
func (m *GPUSliceDevicePlugin) Allocate(ctx context.Context, reqs *pluginapi.AllocateRequest) (*pluginapi.AllocateResponse, error) {
	log.Printf("Allocate called with requests: %v", reqs.ContainerRequests)
	
	responses := make([]*pluginapi.ContainerAllocateResponse, len(reqs.ContainerRequests))
	
	for i, req := range reqs.ContainerRequests {
		log.Printf("Allocating devices: %v", req.DevicesIDs)
		
		// Call GPU manager to allocate slice
		sliceInfo, err := m.allocateSliceFromManager(req.DevicesIDs)
		if err != nil {
			log.Printf("Failed to allocate slice from manager: %v", err)
			return nil, err
		}
		
		// Create device mapping for /dev/nvidia0
		deviceSpecs := []*pluginapi.DeviceSpec{
			{
				ContainerPath: "/dev/nvidia0",
				HostPath:      "/dev/nvidia0",
				Permissions:   "rwm",
			},
			{
				ContainerPath: "/dev/nvidiactl",
				HostPath:      "/dev/nvidiactl", 
				Permissions:   "rwm",
			},
			{
				ContainerPath: "/dev/nvidia-uvm",
				HostPath:      "/dev/nvidia-uvm",
				Permissions:   "rwm",
			},
		}
		
		// Calculate MPS settings for 6 slices
		threadPct := 100 / 6                     // 16% compute per slice
		memLimitMB := 6144 / 6                   // 1024 MB memory per slice
		memLimitStr := fmt.Sprintf("0=%dm", memLimitMB)   // MPS format: "0=1024m"
		
		// Set environment variables for the container
		envs := map[string]string{
			// ✅ ENFORCED by NVIDIA MPS daemon — limits compute to 1/6th
			"CUDA_MPS_ACTIVE_THREAD_PERCENTAGE": fmt.Sprintf("%d", threadPct),
			// ✅ ENFORCED by NVIDIA MPS daemon — limits pinned GPU memory
			"CUDA_MPS_PINNED_DEVICE_MEM_LIMIT": memLimitStr,
			// Standard NVIDIA env vars
			"NVIDIA_VISIBLE_DEVICES": "0",
			"NVIDIA_DRIVER_CAPABILITIES": "compute,utility",
			"CUDA_VISIBLE_DEVICES": "0",
			// For your app's own awareness (informational)
			"GPU_SLICE_ID":           sliceInfo.SliceID,
			"GPU_MEMORY_LIMIT_BYTES": fmt.Sprintf("%d", sliceInfo.MemoryLimitBytes),
			"GPU_THREAD_PCT":         fmt.Sprintf("%d", threadPct),
		}
		
		responses[i] = &pluginapi.ContainerAllocateResponse{
			Devices: deviceSpecs,
			Envs:    envs,
			// ── MPS socket mount — container must reach MPS daemon ──────────
			Mounts: []*pluginapi.Mount{
				{
					ContainerPath: "/tmp/nvidia-mps",
					HostPath:      "/tmp/nvidia-mps",   // MPS daemon creates this socket
					ReadOnly:      false,
				},
			},
		}
	}
	
	return &pluginapi.AllocateResponse{
		ContainerResponses: responses,
	}, nil
}

// SliceAllocation represents allocation info from GPU manager
type SliceAllocation struct {
	SliceID          string `json:"slice_id"`
	MemoryLimitBytes int64  `json:"memory_limit_bytes"`
}

// allocateSliceFromManager calls the GPU manager to allocate a slice
func (m *GPUSliceDevicePlugin) allocateSliceFromManager(deviceIDs []string) (*SliceAllocation, error) {
	managerURL := os.Getenv("GPU_MANAGER_URL")
	if managerURL == "" {
		managerURL = "http://127.0.0.1:5000"
	}
	
	// Generate unique container ID
	containerID := fmt.Sprintf("req-%d-%s", time.Now().Unix(), deviceIDs[0])
	
	// Use the first device ID as the slice ID (slice0, slice1, etc.)
	sliceID := deviceIDs[0]
	
	// Prepare allocation request
	allocReq := map[string]interface{}{
		"container_id": containerID,
		"slice_id":     sliceID,
	}
	
	reqBody, err := json.Marshal(allocReq)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %v", err)
	}
	
	// Retry allocation with backoff
	var resp *http.Response
	for attempt := 0; attempt < 10; attempt++ {
		client := &http.Client{Timeout: 5 * time.Second}
		resp, err = client.Post(managerURL+"/allocate", "application/json", bytes.NewBuffer(reqBody))
		if err == nil && (resp.StatusCode == 200 || resp.StatusCode == 409) {
			break
		}
		
		if resp != nil {
			resp.Body.Close()
		}
		
		log.Printf("Allocation attempt %d failed with status %d: %v", attempt+1, resp.StatusCode, err)
		time.Sleep(time.Duration(attempt+1) * time.Second)
	}
	
	if err != nil {
		return nil, fmt.Errorf("failed to allocate slice after retries: %v", err)
	}
	defer resp.Body.Close()
	
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("allocation failed with status %d: %s", resp.StatusCode, string(body))
	}
	
	// Parse response
	var allocResp struct {
		Status    string `json:"status"`
		SliceID   string `json:"slice_id"`
		MemoryMB  int    `json:"memory_mb"`
		Error     string `json:"error"`
	}
	
	if err := json.NewDecoder(resp.Body).Decode(&allocResp); err != nil {
		return nil, fmt.Errorf("failed to decode response: %v", err)
	}
	
	if allocResp.Status != "allocated" && allocResp.Status != "already_allocated" {
		return nil, fmt.Errorf("allocation failed: %s", allocResp.Error)
	}
	
	// Convert MB to bytes
	memoryLimitBytes := int64(allocResp.MemoryMB) * 1024 * 1024
	
	return &SliceAllocation{
		SliceID:          allocResp.SliceID,
		MemoryLimitBytes: memoryLimitBytes,
	}, nil
}

// GetPreferredAllocation returns the preferred allocation from the set of devices specified in the request
func (m *GPUSliceDevicePlugin) GetPreferredAllocation(context.Context, *pluginapi.PreferredAllocationRequest) (*pluginapi.PreferredAllocationResponse, error) {
	return &pluginapi.PreferredAllocationResponse{}, nil
}

// PreStartContainer is called, if indicated by Device Plugin during registeration phase,
// before each container start. Device plugin can run device specific operations
// such as resetting the device before making devices available to the container
func (m *GPUSliceDevicePlugin) PreStartContainer(context.Context, *pluginapi.PreStartContainerRequest) (*pluginapi.PreStartContainerResponse, error) {
	return &pluginapi.PreStartContainerResponse{}, nil
}

// Start starts the gRPC server of the device plugin
func (m *GPUSliceDevicePlugin) Start() error {
	err := m.cleanup()
	if err != nil {
		return err
	}

	sock, err := net.Listen("unix", m.socket)
	if err != nil {
		return err
	}

	m.server = grpc.NewServer([]grpc.ServerOption{}...)
	pluginapi.RegisterDevicePluginServer(m.server, m)

	go m.server.Serve(sock)

	// Wait for server to start by launching a blocking connection
	conn, err := dial(m.socket, 5*time.Second)
	if err != nil {
		return err
	}
	conn.Close()

	go m.healthcheck()

	return nil
}

// Stop stops the gRPC server
func (m *GPUSliceDevicePlugin) Stop() error {
	if m.server == nil {
		return nil
	}

	m.server.Stop()
	m.server = nil
	close(m.stop)

	return m.cleanup()
}

// Register registers the device plugin for the given resourceName with Kubelet.
func (m *GPUSliceDevicePlugin) Register(kubeletEndpoint, resourceName string) error {
	conn, err := dial(kubeletEndpoint, 5*time.Second)
	if err != nil {
		return err
	}
	defer conn.Close()

	client := pluginapi.NewRegistrationClient(conn)
	reqt := &pluginapi.RegisterRequest{
		Version:      pluginapi.Version,
		Endpoint:     path.Base(m.socket),
		ResourceName: resourceName,
	}

	_, err = client.Register(context.Background(), reqt)
	if err != nil {
		return err
	}
	return nil
}

// healthcheck monitors the health of devices
func (m *GPUSliceDevicePlugin) healthcheck() {
	disableHealthChecks := os.Getenv(envDisableHealthChecks)
	if disableHealthChecks != "" {
		log.Println("Health checks disabled")
		return
	}

	// Simple health check - just keep devices healthy
	// In a real implementation, you'd check actual device status
	for {
		select {
		case <-m.stop:
			return
		default:
			time.Sleep(10 * time.Second)
		}
	}
}

func (m *GPUSliceDevicePlugin) cleanup() error {
	if err := os.Remove(m.socket); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// dial establishes the gRPC communication with the registered device plugin.
func dial(unixSocketPath string, timeout time.Duration) (*grpc.ClientConn, error) {
	c, err := grpc.Dial(unixSocketPath, grpc.WithInsecure(), grpc.WithBlock(),
		grpc.WithTimeout(timeout),
		grpc.WithDialer(func(addr string, timeout time.Duration) (net.Conn, error) {
			return net.DialTimeout("unix", addr, timeout)
		}),
	)

	if err != nil {
		return nil, err
	}

	return c, nil
}