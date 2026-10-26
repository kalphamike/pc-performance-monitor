# PC Performance Monitor (Python) — report only, never auto-fix.
# Run once manually:
#   python monitor.py --top 5 --report "C:\path\to\performance_report.txt"
# Scheduled every 4h via Task Scheduler (see README scheduling section).
# Deps: pip install psutil plyer

import argparse
import datetime
import os
import sys

# --- Optional deps: fail with clear message, don't guess ---
try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)

try:
    from plyer import notification
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False  # notifications optional; console + file always work


def collect(top=5):
    """Collect RAM, CPU totals + per-process usage. Returns dict of measured values."""
    # Total RAM (measured, not estimated)
    mem = psutil.virtual_memory()  # percent, used, total, available
    # Total CPU: block 1s for a real sample (interval=0 would return meaningless 0.0)
    cpu_total = psutil.cpu_percent(interval=1)

    # Per-process CPU needs two samples: prime counters, wait, then read.
    for p in psutil.process_iter():
        try:
            p.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent", "memory_info"]):
        try:
            info = p.info
            # Second cpu_percent call returns % since priming above
            cpu = p.cpu_percent(interval=None)
            ram_pct = info.get("memory_percent") or 0.0
            rss_mb = (info.get("memory_info").rss / (1024 * 1024)) if info.get("memory_info") else 0
            procs.append({
                "name": info.get("name") or "?",
                "pid": info.get("pid"),
                "ram_pct": round(ram_pct, 1),
                "ram_mb": int(rss_mb),
                "cpu": round(cpu, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Top lists are sorted from measured data.
    # Exclude System Idle Process from Top-CPU so real hogs are visible,
    # and exclude this monitor itself so it never flags its own 1s sample.
    own_pid = os.getpid()
    top_ram = sorted(procs, key=lambda x: x["ram_pct"], reverse=True)[:top]
    top_cpu = sorted([p for p in procs if p["pid"] != 0 and p["name"] != "System Idle Process"
                      and p["pid"] != own_pid],
                     key=lambda x: x["cpu"], reverse=True)[:top]
    # Flag: processes using >10% of RAM, or CPU spike (>20% single proc).
    # Note: skip "System Idle Process" (PID 0) — high idle % just means CPU is free.
    heavy_ram = [p for p in procs if p["ram_pct"] > 10.0]
    cpu_spike = [p for p in top_cpu
                 if p["cpu"] > 20.0 and p["pid"] != 0 and p["name"] != "System Idle Process"]

    # Disks: flag LOW <15% free, CRITICAL <10% free.
    # Skip tiny partitions (<10 GB, e.g. recovery) to avoid false alarms.
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            if u.total < 10 * 1024**3:
                continue
            pct_free = round(u.free / u.total * 100, 1)
            flag = "OK"
            if pct_free < 10:
                flag = "CRITICAL"
            elif pct_free < 15:
                flag = "LOW"
            disks.append({"mount": part.mountpoint, "free_gb": round(u.free / 1e9, 1),
                          "total_gb": round(u.total / 1e9, 1), "pct_free": pct_free, "flag": flag})
        except (PermissionError, OSError):
            continue

    boot_ts = psutil.boot_time()
    boot = datetime.datetime.fromtimestamp(boot_ts)
    return {"mem": mem, "cpu_total": cpu_total, "top_ram": top_ram, "top_cpu": top_cpu,
            "heavy_ram": heavy_ram, "cpu_spike": cpu_spike, "disks": disks, "boot": boot}


def suggest(data):
    """Evidence-based suggestions only. Never triggers actions."""
    s = []
    mem_pct = data["mem"].percent
    if mem_pct >= 85:
        s.append("HIGH RAM (>85%): close top RAM apps, restart heavy apps, consider reboot.")
    elif mem_pct >= 75:
        s.append("RAM elevated (>75%): close unused browser tabs/apps.")
    for p in sorted(data["heavy_ram"], key=lambda x: -x["ram_pct"])[:3]:
        s.append(f"Heavy app: {p['name']} (PID {p['pid']}) uses {p['ram_pct']}% RAM ({p['ram_mb']} MB) - close/restart it if not needed.")
    if data["cpu_total"] >= 85:
        s.append(f"CPU spike ({data['cpu_total']}% total): check Top-CPU process before killing anything.")
    for p in data["cpu_spike"][:2]:
        s.append(f"CPU hog: {p['name']} (PID {p['pid']}) at {p['cpu']}% - verify what it is first.")
    for d in data["disks"]:
        if d["flag"] == "CRITICAL":
            s.append(f"{d['mount']} CRITICAL ({d['pct_free']}% free): Disk Cleanup, empty Recycle Bin, move files.")
        elif d["flag"] == "LOW":
            s.append(f"{d['mount']} LOW ({d['pct_free']}% free): plan cleanup soon.")
    # Consistently-high-RAM hint: single snapshot can't prove history — check report file trend
    if mem_pct >= 85:
        s.append("If usage is consistently high across reports: check startup apps (Task Manager > Startup), clean temp files, consider RAM upgrade.")
    if not s:
        s.append("No action needed.")
    return " | ".join(s)


def format_report(data):
    """Exact template — matches PowerShell version for one shared history file."""
    mem = data["mem"]
    total_gb = round(mem.total / 1e9, 2)
    used_gb = round(mem.used / 1e9, 2)
    free_gb = round(mem.available / 1e9, 2)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    up = datetime.datetime.now() - data["boot"]
    days, rem = divmod(int(up.total_seconds()), 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    lines = [f"", f"===== {stamp} =====",
             f"RAM: {used_gb} GB used / {total_gb} GB total ({mem.percent}%) | Free: {free_gb} GB",
             f"CPU (total): {data['cpu_total']}% (avg load)",
             f"--- Top {len(data['top_ram'])} RAM ---"]
    for p in data["top_ram"]:
        lines.append(f"{p['name']} PID={p['pid']} {p['ram_mb']} MB ({p['ram_pct']}%) CPU={p['cpu']}%")
    lines.append(f"--- Top {len(data['top_cpu'])} CPU ---")
    for p in data["top_cpu"]:
        lines.append(f"{p['name']} PID={p['pid']} CPU={p['cpu']}% RAM={p['ram_mb']} MB")
    lines.append("--- Disks ---")
    for d in data["disks"]:
        lines.append(f"{d['mount']} {d['free_gb']} GB free / {d['total_gb']} GB ({d['pct_free']}% free) [{d['flag']}]")
    lines.append(f"Uptime: {days} days {hours}h {mins}m (since {data['boot']})")
    lines.append(f"Suggestions: {suggest(data)}")
    lines.append("----------------------------------------")
    return "\n".join(lines)


def notify(summary):
    """Desktop notification (best-effort). Console output is the real report."""
    if not HAS_NOTIFY:
        return
    try:
        notification.notify(title="PC Performance Monitor", message=summary[:240], timeout=10)
    except Exception as e:
        print(f"(notification skipped: {e})")


def main():
    ap = argparse.ArgumentParser(description="PC Performance Monitor — report only.")
    ap.add_argument("--top", type=int, default=5, help="Top N processes (default 5)")
    ap.add_argument("--report", default=os.path.join(os.getcwd(), "performance_report.txt"),
                    help="Report file path (appends, never overwrites)")
    args = ap.parse_args()

    data = collect(top=args.top)
    report = format_report(data)
    print(report)

    # Append to shared history file; create parent dirs if needed
    parent = os.path.dirname(os.path.abspath(args.report))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    try:
        with open(args.report, "a", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"Saved to: {args.report}")
    except OSError as e:
        print(f"WARNING: could not write report: {e}")

    # Notify with short summary BEFORE any action (no auto-action by design)
    notify(f"RAM {data['mem'].percent}% | CPU {data['cpu_total']}% | Top: "
           + ", ".join(f"{p['name']} {p['ram_pct']}%" for p in data["top_ram"][:2]))


if __name__ == "__main__":
    main()
