# EchoLoom 一键启动：ComfyUI（如未运行）+ Web 工作台
$ErrorActionPreference = "Stop"

function Test-Url($u) {
    try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 3; return $true } catch { return $false }
}

if (-not (Test-Url "http://127.0.0.1:8188/system_stats")) {
    Write-Host "[EchoLoom] 启动 ComfyUI..."
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "D:\develop\comfyui\start.ps1" -WindowStyle Minimized
    $ok = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        if (Test-Url "http://127.0.0.1:8188/system_stats") { $ok = $true; break }
    }
    if (-not $ok) { Write-Error "ComfyUI 120s 内未就绪"; exit 1 }
}
Write-Host "[EchoLoom] ComfyUI 就绪"

Write-Host "[EchoLoom] 启动 Web 工作台 http://127.0.0.1:8199"
Set-Location $PSScriptRoot\..
& .\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8199
