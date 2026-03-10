#!/usr/bin/env python3
"""
Analyze experiment results from baseline and prototype tests
"""

import pandas as pd
import numpy as np

def analyze_csv(filename, test_name):
    """Analyze a single CSV file"""
    try:
        df = pd.read_csv(filename)
        
        print(f"\n=== {test_name} Analysis ===")
        print(f"File: {filename}")
        print(f"Duration: {len(df)} seconds")
        print(f"Active pods: {df['active_pods'].iloc[0]} (consistent: {df['active_pods'].nunique() == 1})")
        
        # GPU utilization stats
        util_mean = df['gpu_util_percent'].mean()
        util_max = df['gpu_util_percent'].max()
        util_std = df['gpu_util_percent'].std()
        
        print(f"GPU Utilization:")
        print(f"  Mean: {util_mean:.1f}%")
        print(f"  Max: {util_max:.1f}%")
        print(f"  Std Dev: {util_std:.1f}%")
        
        # Memory usage stats
        mem_mean = df['gpu_mem_used_mb'].mean()
        mem_max = df['gpu_mem_used_mb'].max()
        mem_std = df['gpu_mem_used_mb'].std()
        
        print(f"GPU Memory Usage:")
        print(f"  Mean: {mem_mean:.1f} MB")
        print(f"  Max: {mem_max:.1f} MB")
        print(f"  Std Dev: {mem_std:.1f} MB")
        
        return {
            'test_name': test_name,
            'duration': len(df),
            'active_pods': df['active_pods'].iloc[0],
            'util_mean': util_mean,
            'util_max': util_max,
            'mem_mean': mem_mean,
            'mem_max': mem_max
        }
        
    except Exception as e:
        print(f"Error analyzing {filename}: {e}")
        return None

def main():
    print("GPU Slice Experiment Results Analysis")
    print("=" * 50)
    
    # Analyze baseline test
    baseline = analyze_csv('baseline.csv', 'Baseline (1 Pod)')
    
    # Analyze prototype test  
    prototype = analyze_csv('experiment_results.csv', 'Prototype (6 Pods)')
    
    # Comparison
    if baseline and prototype:
        print(f"\n=== Comparison ===")
        print(f"Pod scaling: {baseline['active_pods']} → {prototype['active_pods']} pods")
        print(f"GPU utilization change: {baseline['util_mean']:.1f}% → {prototype['util_mean']:.1f}%")
        print(f"GPU memory change: {baseline['mem_mean']:.1f}MB → {prototype['mem_mean']:.1f}MB")
        
        if prototype['active_pods'] > baseline['active_pods']:
            scaling_factor = prototype['active_pods'] / baseline['active_pods']
            print(f"Scaling factor: {scaling_factor:.1f}x")
            
        # Expected vs actual
        print(f"\nExpected behavior:")
        print(f"  - 6 pods should be scheduled and running")
        print(f"  - GPU memory usage should increase with more pods")
        print(f"  - GPU utilization should increase during computation")
        
        print(f"\nActual results:")
        print(f"  - Pods scheduled: {prototype['active_pods']}/6")
        print(f"  - Memory usage: {prototype['mem_mean']:.1f}MB (baseline: {baseline['mem_mean']:.1f}MB)")
        print(f"  - Utilization: {prototype['util_mean']:.1f}% (baseline: {baseline['util_mean']:.1f}%)")

if __name__ == '__main__':
    main()