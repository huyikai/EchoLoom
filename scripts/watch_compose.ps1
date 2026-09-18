# 合成守护：轮询项目状态 → 出片后自动 commit + 重试 push → 写完成标记
param(
    [string]$ProjectId = "6e45b26b02d3",
    [int]$MaxMinutes = 240
)
$root = "D:\develop\EchoLoom"
$marker = "$root\logs\compose_watch_done.txt"
Remove-Item $marker -ErrorAction SilentlyContinue
$deadline = (Get-Date).AddMinutes($MaxMinutes)
$pushed = $false

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8199/api/projects/$ProjectId" -TimeoutSec 10
        $status = $resp.status
        $final = $resp.final
        $err = $resp.error
        Add-Content "$root\logs\compose_watch.log" "$(Get-Date -Format HH:mm:ss) status=$status final=$final err=$err"
        if ($final) {
            # 出片：截图帧留档
            ffmpeg -y -v error -copyts -ss 30 -i "$root\output\$ProjectId\final\mv.mp4" -frames:v 1 "$root\docs\ui-iterations\mv180-frame-a.png" 2>$null
            ffmpeg -y -v error -copyts -ss 90 -i "$root\output\$ProjectId\final\mv.mp4" -frames:v 1 "$root\docs\ui-iterations\mv180-frame-b.png" 2>$null
            ffmpeg -y -v error -copyts -ss 150 -i "$root\output\$ProjectId\final\mv.mp4 -frames:v 1" -frames:v 1 "$root\docs\ui-iterations\mv180-frame-c.png" 2>$null
            Set-Content $marker "DONE final=$final"
            break
        }
        if ($err) { Add-Content "$root\logs\compose_watch.log" "ERROR STOP: $err"; Set-Content $marker "ERROR $err"; break }
    } catch {
        Add-Content "$root\logs\compose_watch.log" "$(Get-Date -Format HH:mm:ss) api unreachable"
    }
    Start-Sleep -Seconds 300
}

# 出片或失败后：提交 + push 重试（最多 40 次，间隔 5 分钟）
for ($i = 1; $i -le 40; $i++) {
    Set-Location $root
    git add -A 2>$null
    git -c core.quotepath=false commit -q -m "M4b: 180s 正式版《雨夜霓虹下的告白》成片与产物存档" 2>$null
    $out = git push https://github.com/huyikai/EchoLoom.git main 2>&1
    if ($LASTEXITCODE -eq 0) { $pushed = $true; Add-Content "$root\logs\compose_watch.log" "PUSH OK at attempt $i"; break }
    Add-Content "$root\logs\compose_watch.log" "push attempt ${i} failed: $out"
    Start-Sleep -Seconds 300
}
Add-Content "$root\logs\compose_watch.log" "watcher exit pushed=$pushed"
