---
name: pc-performance-monitor
description: Monitor Windows PC RAM/CPU performance, generate timestamped reports, and suggest fixes before acting. Use this skill whenever the user asks to check PC, check performance, what is consuming RAM/CPU, monitor PC, setup auto-monitoring, or mentions slow PC, high memory, or performance_report.txt.
---

# PC Performance Monitor

Goal: Monitor RAM/CPU usage, generate a report, notify the user with a summary, suggest solutions, and only act after approval. Supports automatic runs on a schedule via Task Scheduler.

## Workflow

Always follow these steps in order. Do not skip notification/approval.

### 1. Collect system metrics
Run the agent (preferred: monitors AND logs to history DB):
`python <skill-path>/scripts/perf_agent.py --db <history-db> --report <report-path> check --top 5`
Requires `pip install psutil plyer`. Lightweight fallback (no DB): `monitor.py` / `monitor.ps1`.
Default paths: report `performance_report.txt`, history `performance_history.db`, both in working directory.

### 1b. Learn from history (every check, every fix)
- After each check, `recall` is automatic for flagged issues: past fixes + success rates are shown with the report.
- Headless-app flag: every check ranks windowless background processes and raises `headless_app` when a browser runs with zero windows (lingering after close).
- Stale watch: `stale` audits apps not run in 90d (Uninstall registry + Prefetch/UserAssist evidence) and files >=100MB untouched 180d (write-time proxy; Windows disables access-time tracking). Results cache to `stale_report.json`, refreshed weekly by the `PC Stale Audit` task; each `check` prints the top candidates. "No evidence" means unverified, not proven-unused — confirm with the user before removal; redistributables/security deps are never suggested.
- When the user chooses an action: `act --suggestion ID --action "what was done"`.
- After acting, always ask if it worked, then: `outcome --action ID --worked 1|0 --note "..." --ram-before X --ram-after Y`.
- `history --limit N` reviews past reports/actions/outcomes. `recall --kind KIND --detail TEXT` looks up similar cases (kinds: heavy_ram, cpu_hog, disk_critical, disk_low, ram_high).
- Never invent history: only cite rows actually in the DB.

Or collect manually if script is unavailable:
- RAM: `Get-CimInstance Win32_OperatingSystem` -> TotalVisibleMemorySize, FreePhysicalMemory. Compute used % = (total-free)/total*100.
- CPU total: `Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average`
- Top RAM: `Get-Process | Sort-Object WS -Descending | Select-Object -First 5 Name, Id, WS, CPU`
- Top CPU: `Get-Process | Sort-Object CPU -Descending | Select-Object -First 5 Name, Id, CPU`
- Disks: `Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'` -> Size, FreeSpace. Flag <15% free as LOW, <10% as CRITICAL.
- Uptime: `LastBootUpTime` from Win32_OperatingSystem.

Default report path if user does not specify: `performance_report.txt` in current working directory.

### 2. Generate report with timestamp
ALWAYS use this exact template, appended to the report file and shown as summary:

```
===== YYYY-MM-DD HH:MM:SS =====
RAM: X GB used / Y GB total (Z%) | Free: W GB
CPU (total): N% (avg load)
--- Top 5 RAM ---
<Name PID RAM_MB>
--- Top 5 CPU (total time) ---
<Name PID CPU_s>
--- Disks ---
C: X GB free / Y GB (P% free) [OK/LOW/CRITICAL]
Uptime: D days Hh Mm (since BOOT_TIME)
Suggestions: <1-3 lines>
----------------------------------------
```

The script in `scripts/monitor.ps1` already writes this format. Do not invent numbers - use measured values only.

### 3. Save report to file
Append to `performance_report.txt` (default) or user-specified path. Never overwrite history unless user explicitly asks. Confirm file path in your reply.

### 4. Notify user with summary before acting
Reply with short summary:
- RAM % and free GB
- Top 2-3 consumers by name + MB
- Disk flags if LOW/CRITICAL
- Uptime
End with: what do you want to do? Do NOT close apps, kill processes, disable startup items, or delete files without explicit approval for that specific action.

### 5. Suggest solutions (no auto-fix)
Choose only from evidence:
- RAM >85%: close top RAM apps (Edge tabs, Electron apps), check Memory Compression >500MB as pressure sign, suggest reboot if uptime >3 days.
- Single process >1GB (e.g. cmd, msedge, chrome): ask what it is, suggest restart that app.
- C: <15% free: suggest Disk Cleanup, empty Recycle Bin, move files to other drive, uninstall large apps. C: <10% is CRITICAL - state Windows will slow badly.
- High total CPU process (CPU time growing fast between runs): flag as active hog.
- SearchIndexer / Antimalware high: suggest wait for indexing/scan to finish, not kill.
Never suggest registry edits, disabling services, or third-party cleaners.

### 6. Automatic runs via Task Scheduler
Only set up when user explicitly asks for auto-monitoring. Ask for the interval (e.g. every 1 hour). Steps:
1. Confirm script path, report path, DB path, and interval with user.
2. The task runs `run_check.bat` (in working dir), which calls `perf_agent.py check` WITHOUT `--auto`: history is logged and approved rules are only suggested, never executed headlessly, until the user explicitly allows `--auto`.
3. Create task (run in shell, N = interval in hours):
```
schtasks /Create /TN "PC Performance Monitor Py" /TR "<working-dir>\run_check.bat" /SC HOURLY /MO N /F
```
PowerShell alternative: replace /TR with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<skill-script-path>\monitor.ps1' -Top 5 -ReportPath '<report-path>'`.
NOTE: schtasks /TR is limited to 261 chars — always use the .bat wrapper, never inline the full python command.
3. Verify with `schtasks /Query /TN "PC Performance Monitor" /V /FO LIST`.
4. Tell user: runs every 4 hours, report location, how to remove: `schtasks /Delete /TN "PC Performance Monitor" /F`.
5. Never create duplicate tasks without /F or user confirmation. On failure, show scheduler output and fall back to manual runs.

## Edge cases
- Missing counters / access denied: report what succeeded, note what failed, do not guess.
- Laptop vs desktop, HDD vs SSD: do not assume, only state measured disk/RAM numbers.
- If user says just "check my pc": do steps 1-5 once, do not create scheduled task.

## Autonomous rules (only with explicit user approval)
- `propose` derives rule candidates from resolved history (worked >= 1). They are stored UNAPPROVED and inert.
- Present each proposal with its basis (worked N/M) and ask the user to approve, edit, or reject. Never approve rules yourself.
- `approve-rule ID` only on explicit user approval of that rule.
- Approved rules are still suggest-only in interactive `check` ("say 'apply N' to execute"). Headless auto-execution requires the user to explicitly allow `--auto` on the scheduled task. Kill-type rules refuse NEVER_KILL system processes.
- `apply ID` executes one approved rule and logs action+outcome automatically.
