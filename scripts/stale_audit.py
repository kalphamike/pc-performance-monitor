# Stale audit: apps not run in 90+ days + big files untouched 180+ days.
# Evidence (best-effort, read-only):
#   apps  = Uninstall registry (name/size/date) + last-run from Prefetch *.pf
#           mtimes and Explorer UserAssist (ROT13 names, last-run FILETIME).
#           NOTE: evidence can miss portable/store apps -> listed as "unverified".
#   files = last-WRITE time (reliable). Windows usually disables last-ACCESS
#           tracking, so "opened" can't be measured - write-time is the proxy.
# Usage: python stale_audit.py [--out stale_report.json] [--min-mb 100]
import argparse
import codecs
import datetime
import json
import os
import struct
import winreg

NOW = datetime.datetime.now()
APP_DAYS = 90
FILE_DAYS = 180
SKIP_DIRS = {"appdata", ".ollama", "node_modules", ".git", "$recycle.bin",
             "system volume information", "__pycache__"}
# Never suggest removing these (shared libs / game deps, tiny anyway).
SKIP_APP_SUBSTR = ("redistributable", "denuvo", "anti-cheat")


def reg_apps(hive, path):
    """Installed apps from an Uninstall key. Skips updates/components."""
    out = []
    try:
        key = winreg.OpenKey(hive, path)
    except OSError:
        return out
    for i in range(winreg.QueryInfoKey(key)[0]):
        try:
            name = winreg.EnumKey(key, i)
            sk = winreg.OpenKey(key, name)
            def g(v, d=None):
                try:
                    return winreg.QueryValueEx(sk, v)[0]
                except OSError:
                    return d
            disp = g("DisplayName")
            if not disp or g("SystemComponent", 0) == 1:
                continue
            if (g("ReleaseType") or "") in ("Security Update", "Update Rollup", "Hotfix"):
                continue
            if g("ParentKeyName"):
                continue  # patch/child entry, not the app itself
            icon = str(g("DisplayIcon") or "")
            exe = os.path.basename(icon.split(",")[0]).lower() if icon.lower().endswith((".exe", ".exe,0", ".exe,1")) or ".exe" in icon.lower() else ""
            if ".exe" in icon.lower() and not exe:
                exe = os.path.basename(icon.split(",")[0]).lower()
            out.append({"name": disp, "version": str(g("DisplayVersion") or "?"),
                        "publisher": str(g("Publisher") or "?"), "date": str(g("InstallDate") or "?"),
                        "size_kb": g("EstimatedSize", 0) or 0, "exe": exe})
        except OSError:
            continue
    return out


def prefetch_runs():
    """EXE basename -> last-run datetime from Prefetch file mtimes (needs admin)."""
    runs = {}
    try:
        entries = os.listdir(r"C:\Windows\Prefetch")
    except OSError as e:
        print(f"(Prefetch unreadable: {e} - using UserAssist only)")
        return runs
    for fn in entries:
        if not fn.lower().endswith(".pf"):
            continue
        exe = fn.split("-")[0].lower()
        try:
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(r"C:\Windows\Prefetch", fn)))
            if exe not in runs or mt > runs[exe]:
                runs[exe] = mt
        except OSError:
            continue
    return runs


def userassist_runs():
    """EXE basename -> last-run datetime from Explorer UserAssist (best-effort)."""
    runs = {}
    try:
        base = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist")
    except OSError as e:
        print(f"(UserAssist unreadable: {e})")
        return runs
    for gi in range(winreg.QueryInfoKey(base)[0]):
        try:
            gk = winreg.OpenKey(base, winreg.EnumKey(base, gi) + r"\Count")
        except OSError:
            continue
        for vi in range(winreg.QueryInfoKey(gk)[1]):
            try:
                vname, data, _ = winreg.EnumValue(gk, vi)
                plain = codecs.encode(vname, "rot_13").lower()
                if not plain.endswith(".exe") or len(data) < 68:
                    continue
                ft = struct.unpack("<Q", data[60:68])[0]
                if ft == 0:
                    continue
                last = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
                exe = os.path.basename(plain)
                if exe not in runs or last > runs[exe]:
                    runs[exe] = last
            except (OSError, struct.error, OverflowError, ValueError):
                continue
    return runs


def stale_files(roots, min_bytes, cutoff):
    """Big files (size>=min) with last-write older than cutoff. Skips caches."""
    found, scanned = [], 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                    scanned += 1
                except OSError:
                    continue
                if st.st_size >= min_bytes and datetime.datetime.fromtimestamp(st.st_mtime) < cutoff:
                    found.append({"path": fp, "gb": round(st.st_size / 1e9, 2),
                                  "modified": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")})
    found.sort(key=lambda x: -x["gb"])
    return found, scanned


def main():
    ap = argparse.ArgumentParser(description="Stale app/file audit (read-only).")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "stale_report.json"))
    ap.add_argument("--min-mb", type=int, default=100, help="min file size in MB (default 100)")
    ap.add_argument("--home", default=None, help="profile root to scan (default: current user)")
    args = ap.parse_args()

    apps = []
    for hive, sub in [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                      (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]:
        apps.extend(reg_apps(hive, sub))
    seen, uniq = set(), []
    for a in apps:  # de-dupe 32/64-bit twins
        k = (a["name"].lower(), a["version"])
        if k not in seen:
            seen, uniq = seen | {k}, uniq + [a]

    pf, ua = prefetch_runs(), userassist_runs()
    evidence = {**ua, **pf}
    try:
        import psutil
        running = {p.info["name"].lower() for p in psutil.process_iter(["name"])}
    except Exception:
        running = set()
    stale_apps, unverified, skipped = [], [], []
    for a in uniq:
        low = a["name"].lower()
        if any(s in low for s in SKIP_APP_SUBSTR):
            skipped.append(a["name"])
            continue
        first = "".join(ch for ch in low.split(" ")[0] if ch.isalpha())
        if a["exe"] and a["exe"] in running:
            continue  # running right now = in use, regardless of evidence
        if len(first) >= 4 and any(first in r for r in running):
            continue
        last = None
        if a["exe"]:
            cands = [t for e, t in evidence.items() if e == a["exe"]]
            last = max(cands) if cands else None
        if last is None and not a["exe"]:
            unverified.append(a)
        elif last is None or (NOW - last).days > APP_DAYS:
            stale_apps.append({**a, "last_run": last.strftime("%Y-%m-%d") if last else "no evidence",
                               "gb": round(a["size_kb"] / 1e6, 2)})
    stale_apps.sort(key=lambda x: -x["gb"])

    home = args.home or os.path.expanduser("~")
    files, scanned = stale_files([os.path.join(home, d) for d in
                                  ("Documents", "Downloads", "Desktop", "Videos", "Pictures", "OneDrive")],
                                 args.min_mb * 1e6, NOW - datetime.timedelta(days=FILE_DAYS))

    print(f"=== STALE APPS (not run in {APP_DAYS}+d) : {len(stale_apps)} ===")
    for a in stale_apps[:20]:
        print(f"{a['gb']:>7} GB  last={a['last_run']:<12} {a['name'][:60]}")
    print(f"=== UNVERIFIED (no exe to check, review manually): {len(unverified)} ===")
    for a in unverified[:10]:
        print(f"  {a['name'][:70]}")
    print(f"=== STALE FILES (>={args.min_mb}MB, untouched {FILE_DAYS}+d, scanned {scanned}): {len(files)} ===")
    for f in files[:20]:
        print(f"{f['gb']:>7} GB  mod={f['modified']}  {f['path']}")
    print(f"stale apps reclaimable (known sizes): {round(sum(a['gb'] for a in stale_apps), 1)} GB | "
          f"stale files top-listed: {round(sum(f['gb'] for f in files[:20]), 1)} GB")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"generated": NOW.strftime("%Y-%m-%d %H:%M:%S"), "apps": stale_apps,
                   "unverified": [a["name"] for a in unverified], "files": files}, fh)
    print(f"Saved JSON: {args.out}")


if __name__ == "__main__":
    main()
