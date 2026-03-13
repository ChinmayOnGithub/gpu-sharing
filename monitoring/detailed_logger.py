#!/usr/bin/env python3
"""
Detailed Logging System for Fractional GPU Allocation Analysis
Captures comprehensive metrics for ML training and algorithm improvement
"""

import json
import time
import threading
import subprocess
import requests
import sqlite3
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class SystemSnapshot:
    """Complete system state at a point in time"""
    timestamp: float
    datetime_utc: str
    
    # Kubernetes State
    hpa_replicas: int
    hpa_desired_replicas: int
    custom_replicas: int
    custom_desired_replicas: int
    total_running_pods: int
    pending_pods: int
    
    # GPU Resource State
    gpu_slices_total: int
    gpu_slices_allocated: int
    gpu_slices_available: int
    gpu_utilization_percent: float
    gpu_memory_used_mb: int
    gpu_memory_total_mb: int
    gpu_memory_percent: float
    gpu_temperature: int
    
    # Application Metrics
    hpa_app_requests_total: int
    hpa_app_avg_latency_ms: float
    hpa_app_throughput_rps: float
    hpa_app_error_rate: float
    custom_app_requests_total: int
    custom_app_avg_latency_ms: float
    custom_app_throughput_rps: float
    custom_app_error_rate: float
    
    # System Resources
    cpu_percent: float
    memory_percent: float
    load_average_1m: float
    
    # Scaling Events (if any occurred)
    scaling_events: List[Dict[str, Any]]

@dataclass
class ScalingEvent:
    """Individual scaling event details"""
    timestamp: float
    datetime_utc: str
    component: str  # "hpa" or "custom"
    event_type: str  # "scale_up", "scale_down", "no_change"
    old_replicas: int
    new_replicas: int
    trigger_metric: str
    trigger_value: float
    trigger_threshold: float
    decision_reason: str

class DetailedLogger:
    """Comprehensive logging system for fractional GPU allocation analysis"""
    
    def __init__(self, log_dir: str = "logs", db_path: str = "logs/gpu_allocation.db"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.db_path = db_path
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize database
        self._init_database()
        
        # Monitoring state
        self.monitoring = False
        self.monitor_thread = None
        self.collection_interval = 1.0  # seconds
        
        # Kubernetes command prefix
        self.kubectl_cmd = "sudo kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml"
        
        # Application URLs
        self.hpa_url = "http://localhost:8003"
        self.custom_url = "http://localhost:8004"
        
        logger.info(f"DetailedLogger initialized - Session: {self.session_id}")
    
    def _init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # System snapshots table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp REAL,
                datetime_utc TEXT,
                data JSON
            )
        ''')
        
        # Scaling events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scaling_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp REAL,
                datetime_utc TEXT,
                component TEXT,
                event_type TEXT,
                old_replicas INTEGER,
                new_replicas INTEGER,
                trigger_metric TEXT,
                trigger_value REAL,
                trigger_threshold REAL,
                decision_reason TEXT
            )
        ''')
        
        # Experiment sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS experiment_sessions (
                session_id TEXT PRIMARY KEY,
                start_time REAL,
                end_time REAL,
                experiment_type TEXT,
                description TEXT,
                config JSON
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def start_monitoring(self, experiment_type: str = "general", description: str = ""):
        """Start continuous monitoring and logging"""
        if self.monitoring:
            logger.warning("Monitoring already active")
            return
        
        # Record experiment session
        self._record_experiment_session(experiment_type, description)
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        
        logger.info(f"Started monitoring - Type: {experiment_type}")
    
    def stop_monitoring(self):
        """Stop monitoring and finalize session"""
        if not self.monitoring:
            logger.warning("Monitoring not active")
            return
        
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        # Update session end time
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE experiment_sessions 
            SET end_time = ? 
            WHERE session_id = ?
        ''', (time.time(), self.session_id))
        conn.commit()
        conn.close()
        
        logger.info("Monitoring stopped and session finalized")
    
    def _monitoring_loop(self):
        """Main monitoring loop - collects data every second"""
        last_replicas = {"hpa": 0, "custom": 0}
        
        while self.monitoring:
            try:
                # Collect system snapshot
                snapshot = self._collect_system_snapshot()
                
                # Check for scaling events
                scaling_events = []
                
                # HPA scaling event detection
                if snapshot.hpa_replicas != last_replicas["hpa"]:
                    event = ScalingEvent(
                        timestamp=snapshot.timestamp,
                        datetime_utc=snapshot.datetime_utc,
                        component="hpa",
                        event_type="scale_up" if snapshot.hpa_replicas > last_replicas["hpa"] else "scale_down",
                        old_replicas=last_replicas["hpa"],
                        new_replicas=snapshot.hpa_replicas,
                        trigger_metric="cpu_percent",
                        trigger_value=snapshot.cpu_percent,
                        trigger_threshold=50.0,
                        decision_reason=f"CPU utilization {snapshot.cpu_percent}% vs 50% threshold"
                    )
                    scaling_events.append(event)
                    self._record_scaling_event(event)
                
                # Custom scaling event detection
                if snapshot.custom_replicas != last_replicas["custom"]:
                    event = ScalingEvent(
                        timestamp=snapshot.timestamp,
                        datetime_utc=snapshot.datetime_utc,
                        component="custom",
                        event_type="scale_up" if snapshot.custom_replicas > last_replicas["custom"] else "scale_down",
                        old_replicas=last_replicas["custom"],
                        new_replicas=snapshot.custom_replicas,
                        trigger_metric="gpu_utilization_percent",
                        trigger_value=snapshot.gpu_utilization_percent,
                        trigger_threshold=70.0,
                        decision_reason=f"GPU utilization {snapshot.gpu_utilization_percent}% vs 70% threshold"
                    )
                    scaling_events.append(event)
                    self._record_scaling_event(event)
                
                # Update snapshot with scaling events
                snapshot.scaling_events = [asdict(event) for event in scaling_events]
                
                # Record snapshot
                self._record_system_snapshot(snapshot)
                
                # Update last known replicas
                last_replicas["hpa"] = snapshot.hpa_replicas
                last_replicas["custom"] = snapshot.custom_replicas
                
                # Wait for next collection
                time.sleep(self.collection_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.collection_interval)
    
    def _collect_system_snapshot(self) -> SystemSnapshot:
        """Collect complete system state snapshot"""
        timestamp = time.time()
        datetime_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        
        # Kubernetes state
        hpa_replicas = self._get_replicas("hpa-fractional-app")
        hpa_desired = self._get_desired_replicas("hpa-fractional-app")
        custom_replicas = self._get_replicas("custom-fractional-app")
        custom_desired = self._get_desired_replicas("custom-fractional-app")
        
        # Pod counts
        total_running, pending = self._get_pod_counts()
        
        # GPU resource state
        gpu_state = self._get_gpu_resource_state()
        
        # Application metrics
        hpa_metrics = self._get_app_metrics(self.hpa_url)
        custom_metrics = self._get_app_metrics(self.custom_url)
        
        # System resources
        cpu_percent, memory_percent, load_avg = self._get_system_resources()
        
        return SystemSnapshot(
            timestamp=timestamp,
            datetime_utc=datetime_utc,
            hpa_replicas=hpa_replicas,
            hpa_desired_replicas=hpa_desired,
            custom_replicas=custom_replicas,
            custom_desired_replicas=custom_desired,
            total_running_pods=total_running,
            pending_pods=pending,
            gpu_slices_total=gpu_state["total"],
            gpu_slices_allocated=gpu_state["allocated"],
            gpu_slices_available=gpu_state["available"],
            gpu_utilization_percent=gpu_state["utilization"],
            gpu_memory_used_mb=gpu_state["memory_used"],
            gpu_memory_total_mb=gpu_state["memory_total"],
            gpu_memory_percent=gpu_state["memory_percent"],
            gpu_temperature=gpu_state["temperature"],
            hpa_app_requests_total=hpa_metrics["requests"],
            hpa_app_avg_latency_ms=hpa_metrics["latency"],
            hpa_app_throughput_rps=hpa_metrics["throughput"],
            hpa_app_error_rate=hpa_metrics["error_rate"],
            custom_app_requests_total=custom_metrics["requests"],
            custom_app_avg_latency_ms=custom_metrics["latency"],
            custom_app_throughput_rps=custom_metrics["throughput"],
            custom_app_error_rate=custom_metrics["error_rate"],
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            load_average_1m=load_avg,
            scaling_events=[]  # Will be populated by monitoring loop
        )
    
    def _get_replicas(self, deployment: str) -> int:
        """Get current replica count for deployment"""
        try:
            cmd = f"{self.kubectl_cmd} get deployment {deployment} -o jsonpath='{{.status.readyReplicas}}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return int(result.stdout.strip() or "0")
        except:
            return 0
    
    def _get_desired_replicas(self, deployment: str) -> int:
        """Get desired replica count for deployment"""
        try:
            cmd = f"{self.kubectl_cmd} get deployment {deployment} -o jsonpath='{{.spec.replicas}}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return int(result.stdout.strip() or "0")
        except:
            return 0
    
    def _get_pod_counts(self) -> tuple:
        """Get running and pending pod counts"""
        try:
            # Running pods
            cmd = f"{self.kubectl_cmd} get pods --field-selector=status.phase=Running --no-headers | wc -l"
            running_result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            running = int(running_result.stdout.strip() or "0")
            
            # Pending pods
            cmd = f"{self.kubectl_cmd} get pods --field-selector=status.phase=Pending --no-headers | wc -l"
            pending_result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            pending = int(pending_result.stdout.strip() or "0")
            
            return running, pending
        except:
            return 0, 0
    
    def _get_gpu_resource_state(self) -> Dict[str, Any]:
        """Get GPU resource allocation state"""
        try:
            # Get allocated slices
            cmd = f"{self.kubectl_cmd} get pods -o json"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                import json
                pods_data = json.loads(result.stdout)
                allocated_slices = 0
                
                for pod in pods_data.get("items", []):
                    if pod.get("status", {}).get("phase") == "Running":
                        for container in pod.get("spec", {}).get("containers", []):
                            resources = container.get("resources", {}).get("requests", {})
                            if "example.com/gpu-slice" in resources:
                                allocated_slices += int(resources["example.com/gpu-slice"])
            else:
                allocated_slices = 0
            
            # Get GPU metrics via nvidia-smi
            gpu_metrics = self._get_nvidia_smi_metrics()
            
            return {
                "total": 6,
                "allocated": allocated_slices,
                "available": 6 - allocated_slices,
                "utilization": gpu_metrics["utilization"],
                "memory_used": gpu_metrics["memory_used"],
                "memory_total": gpu_metrics["memory_total"],
                "memory_percent": gpu_metrics["memory_percent"],
                "temperature": gpu_metrics["temperature"]
            }
        except:
            return {
                "total": 6, "allocated": 0, "available": 6,
                "utilization": 0, "memory_used": 0, "memory_total": 6144,
                "memory_percent": 0, "temperature": 0
            }
    
    def _get_nvidia_smi_metrics(self) -> Dict[str, float]:
        """Get GPU metrics from nvidia-smi"""
        try:
            cmd = "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                values = result.stdout.strip().split(', ')
                return {
                    "utilization": float(values[0]),
                    "memory_used": int(values[1]),
                    "memory_total": int(values[2]),
                    "memory_percent": (int(values[1]) / int(values[2])) * 100,
                    "temperature": int(values[3])
                }
        except:
            pass
        
        return {"utilization": 0, "memory_used": 0, "memory_total": 6144, "memory_percent": 0, "temperature": 0}
    
    def _get_app_metrics(self, url: str) -> Dict[str, float]:
        """Get application metrics from /metrics endpoint"""
        try:
            response = requests.get(f"{url}/metrics", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return {
                    "requests": data.get("request_count", 0),
                    "latency": data.get("avg_latency_ms", 0),
                    "throughput": data.get("request_count", 0) / max(data.get("uptime_s", 1), 1),
                    "error_rate": 0  # Calculate from success rate if available
                }
        except:
            pass
        
        return {"requests": 0, "latency": 0, "throughput": 0, "error_rate": 0}
    
    def _get_system_resources(self) -> tuple:
        """Get system CPU, memory, and load average"""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
            load_avg = psutil.getloadavg()[0]
            return cpu_percent, memory_percent, load_avg
        except:
            return 0.0, 0.0, 0.0
    
    def _record_experiment_session(self, experiment_type: str, description: str):
        """Record experiment session start"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO experiment_sessions 
            (session_id, start_time, experiment_type, description, config)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            self.session_id,
            time.time(),
            experiment_type,
            description,
            json.dumps({"collection_interval": self.collection_interval})
        ))
        
        conn.commit()
        conn.close()
    
    def _record_system_snapshot(self, snapshot: SystemSnapshot):
        """Record system snapshot to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO system_snapshots 
            (session_id, timestamp, datetime_utc, data)
            VALUES (?, ?, ?, ?)
        ''', (
            self.session_id,
            snapshot.timestamp,
            snapshot.datetime_utc,
            json.dumps(asdict(snapshot))
        ))
        
        conn.commit()
        conn.close()
    
    def _record_scaling_event(self, event: ScalingEvent):
        """Record scaling event to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO scaling_events 
            (session_id, timestamp, datetime_utc, component, event_type, 
             old_replicas, new_replicas, trigger_metric, trigger_value, 
             trigger_threshold, decision_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            self.session_id,
            event.timestamp,
            event.datetime_utc,
            event.component,
            event.event_type,
            event.old_replicas,
            event.new_replicas,
            event.trigger_metric,
            event.trigger_value,
            event.trigger_threshold,
            event.decision_reason
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Scaling event recorded: {event.component} {event.event_type} {event.old_replicas}->{event.new_replicas}")
    
    def export_session_data(self, session_id: Optional[str] = None, format: str = "csv") -> str:
        """Export session data for analysis"""
        if session_id is None:
            session_id = self.session_id
        
        conn = sqlite3.connect(self.db_path)
        
        # Export system snapshots
        snapshots_df = pd.read_sql_query('''
            SELECT * FROM system_snapshots 
            WHERE session_id = ?
            ORDER BY timestamp
        ''', conn, params=(session_id,))
        
        # Export scaling events
        events_df = pd.read_sql_query('''
            SELECT * FROM scaling_events 
            WHERE session_id = ?
            ORDER BY timestamp
        ''', conn, params=(session_id,))
        
        conn.close()
        
        # Save to files
        output_dir = self.log_dir / f"export_{session_id}"
        output_dir.mkdir(exist_ok=True)
        
        if format == "csv":
            snapshots_file = output_dir / "system_snapshots.csv"
            events_file = output_dir / "scaling_events.csv"
            
            snapshots_df.to_csv(snapshots_file, index=False)
            events_df.to_csv(events_file, index=False)
            
            logger.info(f"Data exported to {output_dir}")
            return str(output_dir)
        
        elif format == "json":
            snapshots_file = output_dir / "system_snapshots.json"
            events_file = output_dir / "scaling_events.json"
            
            snapshots_df.to_json(snapshots_file, orient="records", indent=2)
            events_df.to_json(events_file, orient="records", indent=2)
            
            logger.info(f"Data exported to {output_dir}")
            return str(output_dir)
    
    def get_session_summary(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get summary statistics for a session"""
        if session_id is None:
            session_id = self.session_id
        
        conn = sqlite3.connect(self.db_path)
        
        # Session info
        session_info = pd.read_sql_query('''
            SELECT * FROM experiment_sessions WHERE session_id = ?
        ''', conn, params=(session_id,)).iloc[0].to_dict()
        
        # Scaling events summary
        events_summary = pd.read_sql_query('''
            SELECT component, event_type, COUNT(*) as count
            FROM scaling_events 
            WHERE session_id = ?
            GROUP BY component, event_type
        ''', conn, params=(session_id,))
        
        # System metrics summary
        snapshots_df = pd.read_sql_query('''
            SELECT data FROM system_snapshots 
            WHERE session_id = ?
            ORDER BY timestamp
        ''', conn, params=(session_id,))
        
        conn.close()
        
        # Parse snapshot data for statistics
        if not snapshots_df.empty:
            snapshot_data = []
            for _, row in snapshots_df.iterrows():
                snapshot_data.append(json.loads(row['data']))
            
            metrics_df = pd.DataFrame(snapshot_data)
            
            summary = {
                "session_info": session_info,
                "duration_seconds": session_info.get("end_time", time.time()) - session_info["start_time"],
                "total_snapshots": len(snapshot_data),
                "scaling_events": events_summary.to_dict("records"),
                "metrics_summary": {
                    "max_hpa_replicas": int(metrics_df["hpa_replicas"].max()),
                    "max_custom_replicas": int(metrics_df["custom_replicas"].max()),
                    "max_gpu_utilization": float(metrics_df["gpu_utilization_percent"].max()),
                    "avg_gpu_utilization": float(metrics_df["gpu_utilization_percent"].mean()),
                    "max_gpu_slices_used": int(metrics_df["gpu_slices_allocated"].max()),
                    "avg_throughput_hpa": float(metrics_df["hpa_app_throughput_rps"].mean()),
                    "avg_throughput_custom": float(metrics_df["custom_app_throughput_rps"].mean())
                }
            }
        else:
            summary = {
                "session_info": session_info,
                "duration_seconds": 0,
                "total_snapshots": 0,
                "scaling_events": [],
                "metrics_summary": {}
            }
        
        return summary

if __name__ == "__main__":
    # Example usage
    logger = DetailedLogger()
    
    print("Starting detailed monitoring...")
    logger.start_monitoring("test_experiment", "Testing detailed logging system")
    
    try:
        # Monitor for 30 seconds
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    
    logger.stop_monitoring()
    
    # Export data
    export_path = logger.export_session_data(format="csv")
    print(f"Data exported to: {export_path}")
    
    # Print summary
    summary = logger.get_session_summary()
    print("\nSession Summary:")
    print(json.dumps(summary, indent=2, default=str))