#!/usr/bin/env powershell

$OUT = "experiment_results.csv"
"timestamp,gpu_util_percent,gpu_mem_used_mb,active_pods" | Out-File -FilePath $OUT -Encoding UTF8

for ($i = 1; $i -le 60; $i++) {
    $ts = [int][double]::Parse((Get-Date -UFormat %s))
    
    try {
        $util = (nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits) -replace '\s',''
        $mem = (nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s',''
        $active = (kubectl get pods --no-headers | Select-String "gpu-test-pod" | Measure-Object).Count
        
        "$ts,$util,$mem,$active" | Out-File -FilePath $OUT -Append -Encoding UTF8
        Write-Host "[$i/60] ts=$ts util=$util% mem=${mem}MB active=$active"
    }
    catch {
        Write-Host "Error collecting metrics: $_"
        "$ts,0,0,0" | Out-File -FilePath $OUT -Append -Encoding UTF8
    }
    
    Start-Sleep -Seconds 1
}

Write-Host "Saved metrics to $OUT"