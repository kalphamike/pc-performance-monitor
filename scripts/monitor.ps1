# PC Performance Monitor - bundled script
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 -Top 5 -ReportPath "C:\path\to\performance_report.txt"
param(
  [int]$Top = 5,
  [string]$ReportPath = (Join-Path (Get-Location) "performance_report.txt")
)

$os = Get-CimInstance Win32_OperatingSystem
$totalKB = $os.TotalVisibleMemorySize
$freeKB = $os.FreePhysicalMemory
$usedKB = $totalKB - $freeKB
$usedPct = [math]::Round($usedKB / $totalKB * 100, 1)
$totalGB = [math]::Round($totalKB / 1MB, 2)
$usedGB = [math]::Round($usedKB / 1MB, 2)
$freeGB = [math]::Round($freeKB / 1MB, 2)

$cpuAvg = $null
try {
  $cpuAvg = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
  $cpuAvg = [math]::Round($cpuAvg, 1)
} catch { $cpuAvg = "n/a" }

$boot = $os.LastBootUpTime
$uptime = (Get-Date) - $boot
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$topRam = Get-Process | Sort-Object WS -Descending | Select-Object -First $Top Name, Id,
  @{N='RAM_MB';E={[int]($_.WS/1MB)}}, CPU

$topCpu = Get-Process | Sort-Object CPU -Descending | Select-Object -First $Top Name, Id, CPU

$disks = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'

$suggestions = @()
if ($usedPct -ge 85) { $suggestions += "HIGH RAM (>85%): close top RAM apps, restart heavy apps, consider reboot." }
elseif ($usedPct -ge 75) { $suggestions += "RAM elevated (>75%): close unused browser tabs/apps." }
$bigProc = $topRam | Where-Object { $_.RAM_MB -gt 1000 } | Select-Object -First 1
if ($bigProc) { $suggestions += ("Single process >1GB: {0} (PID {1}, {2} MB) - verify what it is before closing." -f $bigProc.Name, $bigProc.Id, $bigProc.RAM_MB) }
foreach ($d in $disks) {
  $pctFree = [math]::Round($d.FreeSpace / $d.Size * 100, 1)
  if ($pctFree -lt 10) { $suggestions += ("{0} CRITICAL ({1}% free): free space now - Disk Cleanup, empty Recycle Bin, move files." -f $d.DeviceID, $pctFree) }
  elseif ($pctFree -lt 15) { $suggestions += ("{0} LOW ({1}% free): plan cleanup soon." -f $d.DeviceID, $pctFree) }
}
if ($uptime.Days -ge 3) { $suggestions += ("Uptime {0} days: reboot can clear leaks." -f $uptime.Days) }
if ($suggestions.Count -eq 0) { $suggestions += "No action needed." }
$suggestLine = $suggestions -join " | "

$lines = @()
$lines += ""
$lines += "===== $stamp ====="
$lines += ("RAM: {0} GB used / {1} GB total ({2}%) | Free: {3} GB" -f $usedGB, $totalGB, $usedPct, $freeGB)
$lines += ("CPU (total): {0}% (avg load)" -f $cpuAvg)
$lines += "--- Top $Top RAM ---"
foreach ($p in $topRam) { $lines += ("{0} PID={1} {2} MB CPU={3}s" -f $p.Name, $p.Id, $p.RAM_MB, [math]::Round($p.CPU,1)) }
$lines += "--- Top $Top CPU (total time) ---"
foreach ($p in $topCpu) { $lines += ("{0} PID={1} CPU={2}s" -f $p.Name, $p.Id, [math]::Round($p.CPU,1)) }
$lines += "--- Disks ---"
foreach ($d in $disks) {
  $pctFree = [math]::Round($d.FreeSpace / $d.Size * 100, 1)
  $flag = "OK"
  if ($pctFree -lt 10) { $flag = "CRITICAL" } elseif ($pctFree -lt 15) { $flag = "LOW" }
  $lines += ("{0} {1} GB free / {2} GB ({3}% free) [{4}]" -f $d.DeviceID, [math]::Round($d.FreeSpace/1GB,1), [math]::Round($d.Size/1GB,1), $pctFree, $flag)
}
$lines += ("Uptime: {0} days {1}h {2}m (since {3})" -f $uptime.Days, $uptime.Hours, $uptime.Minutes, $boot)
$lines += ("Suggestions: $suggestLine")
$lines += "----------------------------------------"

$report = $lines -join [Environment]::NewLine
Write-Host $report
try {
  $dir = Split-Path -Parent $ReportPath
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  Add-Content -Path $ReportPath -Value $report -Encoding UTF8
  Write-Host ("Saved to: $ReportPath") -ForegroundColor Cyan
} catch {
  Write-Warning ("Could not write report to {0}: {1}" -f $ReportPath, $_.Exception.Message)
}
