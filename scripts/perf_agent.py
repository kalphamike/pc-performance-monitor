# PC Performance Agent — monitor + learn + propose. Report-first, never auto-acts
# unless a rule was explicitly approved AND run via `apply` / `check --auto`.
#
# Commands (run from any shell):
#   python perf_agent.py init [--db FILE]
#       Create performance_history.db and seed today's session (only if empty).
#   python perf_agent.py check [--top 5] [--report FILE] [--db FILE] [--auto]
#       Collect metrics, append performance_report.txt, save report+suggestions
#       to the DB, notify, show recalled past fixes. --auto executes APPROVED
#       rules headlessly (for Task Scheduler, only after you approve rules).
#   python perf_agent.py act --suggestion ID --action "what you did"
#       Log the action you chose for a suggestion.
#   python perf_agent.py outcome --action ID --worked 1|0 [--note "..."]
#       Log whether the action worked. This is what the agent learns from.
#   python perf_agent.py history [--limit 10]   Show past reports/actions/outcomes.
#   python perf_agent.py recall --kind KIND [--detail TEXT]
#       Show similar past cases + success rates. Kinds: heavy_ram, cpu_hog,
#       headless_app, disk_critical, disk_low, ram_high.
#   python perf_agent.py stale [--min-mb 100]
#       Unused-app (90d+) + untouched-file (180d+, >=min-mb) audit for
#       uninstall/archive decisions. Saved to stale_report.json (weekly job).
#   python perf_agent.py propose   Propose autonomous rules from history (stored
#       as UNAPPROVED — nothing acts until you run approve-rule).
#   python perf_agent.py approve-rule ID   Approve a proposed rule.
#   python perf_agent.py rules   List rules and their approval state.
#   python perf_agent.py apply ID   Execute one APPROVED rule now.
#
# Deps: pip install psutil plyer

import argparse
import datetime
import json
import os
import sqlite3
import sys

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)

try:
    from plyer import notification
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

# Safety: apply will NEVER kill these, even if a rule says so.
NEVER_KILL = {"System", "Registry", "smss.exe", "csrss.exe", "wininit.exe",
              "services.exe", "lsass.exe", "dwm.exe", "explorer.exe",
              "System Idle Process"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY, ts TEXT, ram_pct REAL, ram_used_gb REAL,
  ram_total_gb REAL, cpu_pct REAL, top_json TEXT, disks_json TEXT, uptime TEXT);
CREATE TABLE IF NOT EXISTS suggestions(
  id INTEGER PRIMARY KEY, report_id INTEGER, kind TEXT, detail TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS actions(
  id INTEGER PRIMARY KEY, suggestion_id INTEGER, action TEXT, ts TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS outcomes(
  id INTEGER PRIMARY KEY, action_id INTEGER, worked INTEGER, note TEXT,
  ram_before REAL, ram_after REAL, ts TEXT);
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY, cond_json TEXT, action_json TEXT,
  approved INTEGER DEFAULT 0, basis TEXT);
"""


def db(path):
    """Open (creating) the history DB and ensure schema exists."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def collect(top=5):
    """Measure RAM/CPU/processes/disks. Returns (data, suggestions)."""
    mem = psutil.virtual_memory()
    cpu_total = psutil.cpu_percent(interval=1)
    for p in psutil.process_iter():  # prime per-process CPU counters
        try:
            p.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    own = os.getpid()
    # Visible windows (Windows only): powers the "runs while closed" check.
    visible = set()
    try:
        import ctypes
        _u32 = ctypes.windll.user32

        _cbtype = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @_cbtype
        def _cb(hwnd, _):
            if _u32.IsWindowVisible(hwnd):
                _pid = ctypes.c_ulong()
                _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(_pid))
                visible.add(_pid.value)
            return True

        _u32.EnumWindows(_cb, 0)
    except Exception:
        visible = set()  # non-Windows or locked down: bg section stays empty
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_percent", "memory_info"]):
        try:
            i = p.info
            procs.append({"name": i.get("name") or "?", "pid": i.get("pid"),
                          "user": (i.get("username") or "").split("\\")[-1],
                          "ram_pct": round(i.get("memory_percent") or 0.0, 1),
                          "ram_mb": int(i.get("memory_info").rss / 1024**2) if i.get("memory_info") else 0,
                          "cpu": round(p.cpu_percent(interval=None), 1),
                          "win": i.get("pid") in visible})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    top_ram = sorted(procs, key=lambda x: -x["ram_pct"])[:top]
    top_cpu = sorted([p for p in procs if p["pid"] not in (0, own)
                      and p["name"] != "System Idle Process"],
                     key=lambda x: -x["cpu"])[:top]
    # Background ranking: user-session processes with no visible window.
    bg_top = sorted([p for p in procs if not p["win"] and p["user"] not in
                     ("SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "")],
                    key=lambda x: -x["ram_mb"])[:5]
    # Headless browsers: alive with zero windows = lingering after close.
    headless = []
    for _b in ("msedge.exe", "chrome.exe", "opera.exe", "firefox.exe"):
        _fam = [p for p in procs if p["name"] == _b]
        if _fam and not any(p["win"] for p in _fam):
            headless.append((_b, sum(p["ram_mb"] for p in _fam)))
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            if u.total < 10 * 1024**3:  # skip tiny recovery partitions
                continue
            pf = round(u.free / u.total * 100, 1)
            disks.append({"mount": part.mountpoint, "free_gb": round(u.free / 1e9, 1),
                          "total_gb": round(u.total / 1e9, 1), "pct_free": pf,
                          "flag": "CRITICAL" if pf < 10 else ("LOW" if pf < 15 else "OK")})
        except (PermissionError, OSError):
            continue
    boot = datetime.datetime.fromtimestamp(psutil.boot_time())
    data = {"mem": mem, "cpu_total": cpu_total, "top_ram": top_ram,
            "top_cpu": top_cpu, "disks": disks, "boot": boot,
            "bg_top": bg_top, "headless": headless}

    # Suggestions carry (kind, detail) so history can match similar issues later.
    sug = []
    if mem.percent >= 85:
        sug.append(("ram_high", "", "HIGH RAM (>85%): close top RAM apps, restart heavy apps, consider reboot."))
    elif mem.percent >= 75:
        sug.append(("ram_high", "", "RAM elevated (>75%): close unused browser tabs/apps."))
    for p in sorted([x for x in procs if x["ram_pct"] > 10.0], key=lambda x: -x["ram_pct"])[:3]:
        sug.append(("heavy_ram", p["name"],
                    f"Heavy app: {p['name']} (PID {p['pid']}) uses {p['ram_pct']}% RAM ({p['ram_mb']} MB) - verify, then close/restart."))
    for p in [x for x in top_cpu if x["cpu"] > 20.0][:2]:
        sug.append(("cpu_hog", p["name"],
                    f"CPU hog: {p['name']} (PID {p['pid']}) at {p['cpu']}% - verify what it is first."))
    for bname, mb in headless:
        sug.append(("headless_app", bname,
                    f"{bname} running with NO windows ({mb} MB) - lingering after close; "
                    f"turn off 'continue running background apps' or end the task."))
    for d in disks:
        if d["flag"] == "CRITICAL":
            sug.append(("disk_critical", d["mount"],
                        f"{d['mount']} CRITICAL ({d['pct_free']}% free): Disk Cleanup, empty Recycle Bin, move files."))
        elif d["flag"] == "LOW":
            sug.append(("disk_low", d["mount"], f"{d['mount']} LOW ({d['pct_free']}% free): plan cleanup soon."))
    if not sug:
        sug.append(("ok", "", "No action needed."))
    return data, sug


def format_report(data, sug):
    """Same text template as monitor.py so one shared history file works."""
    mem = data["mem"]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    up = datetime.datetime.now() - data["boot"]
    d, r = divmod(int(up.total_seconds()), 86400)
    h, r = divmod(r, 3600)
    lines = [f"", f"===== {stamp} =====",
             f"RAM: {round(mem.used/1e9,2)} GB used / {round(mem.total/1e9,2)} GB total ({mem.percent}%) | Free: {round(mem.available/1e9,2)} GB",
             f"CPU (total): {data['cpu_total']}% (avg load)",
             f"--- Top {len(data['top_ram'])} RAM ---"]
    lines += [f"{p['name']} PID={p['pid']} {p['ram_mb']} MB ({p['ram_pct']}%) CPU={p['cpu']}%" for p in data["top_ram"]]
    lines.append(f"--- Top {len(data['top_cpu'])} CPU ---")
    lines += [f"{p['name']} PID={p['pid']} CPU={p['cpu']}% RAM={p['ram_mb']} MB" for p in data["top_cpu"]]
    lines.append("--- Background (no window, top 5) ---")
    lines += [f"{p['name']} PID={p['pid']} {p['ram_mb']} MB ({p['ram_pct']}%)" for p in data.get("bg_top", [])]
    for bname, mb in data.get("headless", []):
        lines.append(f"HEADLESS: {bname} alive with 0 windows ({mb} MB)")
    lines.append("--- Disks ---")
    lines += [f"{x['mount']} {x['free_gb']} GB free / {x['total_gb']} GB ({x['pct_free']}% free) [{x['flag']}]" for x in data["disks"]]
    lines.append(f"Uptime: {d} days {h}h {r//60}m (since {data['boot']})")
    lines.append("Suggestions: " + " | ".join(t for _, _, t in sug))
    lines.append("----------------------------------------")
    return "\n".join(lines)


def notify(msg):
    """Best-effort desktop toast; console output is the real report."""
    if HAS_NOTIFY:
        try:
            notification.notify(title="PC Performance Agent", message=msg[:240], timeout=10)
        except Exception as e:
            print(f"(notification skipped: {e})")


def seed(conn):
    """Insert a SAMPLE session (a real cmd-kill / disk-move / extension-block
    workflow) so recall/propose demonstrate value on a fresh DB.
    Only runs on an empty DB. Replace with your own history over time."""
    if conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]:
        print("DB already has data, seed skipped.")
        return
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seeds = [
        # (report_ram, suggestion, action, worked, note, ram_before, ram_after)
        (66.4, ("heavy_ram", "cmd.exe", "Heavy app cmd.exe 2GB orphaned"),
         "Killed PID 17852 (orphaned cmd, parent dead, no children)", 1,
         "RAM 66.4->63.5%, CPU 25->4.7%", 66.4, 63.5),
        (8.3, ("disk_critical", "C:\\", "C: 8.3% free CRITICAL"),
         "Moved Ollama models (33GB) to E:, set OLLAMA_MODELS (junction failed, direct serve worked)", 1,
         "C: 8.3->22.3% free; tray app cannot follow junctions", 8.3, 22.3),
        (73.2, ("heavy_ram", "msedge.exe", "LinkedIn renderer 2.3GB + 26 extensions all ON"),
         "Blocklisted all Edge extensions via policy + restarted Edge", 1,
         "RAM 73.2->60.8%, extension procs 7->0", 73.2, 60.8),
    ]
    for ram, (kind, detail, text), action, worked, note, rb, ra in seeds:
        rid = conn.execute(
            "INSERT INTO reports(ts,ram_pct,ram_used_gb,ram_total_gb,cpu_pct,top_json,disks_json,uptime)"
            " VALUES(?,?,?,?,?,?,?,?)", (now, ram, 0, 17.01, 0, "[]", "[]", "")).lastrowid
        sid = conn.execute(
            "INSERT INTO suggestions(report_id,kind,detail,text) VALUES(?,?,?,?)",
            (rid, kind, detail, text)).lastrowid
        aid = conn.execute(
            "INSERT INTO actions(suggestion_id,action,ts,status) VALUES(?,?,?,?)",
            (sid, action, now, "done")).lastrowid
        conn.execute(
            "INSERT INTO outcomes(action_id,worked,note,ram_before,ram_after,ts)"
            " VALUES(?,?,?,?,?,?)", (aid, worked, note, rb, ra, now))
    conn.commit()
    print("Seeded 3 sessions from today (cmd kill, Ollama move, extension blocklist).")


def recall(conn, kind, detail=""):
    """Past cases of this kind (+detail), ranked with success rates."""
    q = """SELECT s.kind, s.detail, s.text, a.action, o.worked, o.note, r.ts
           FROM suggestions s JOIN actions a ON a.suggestion_id=s.id
           JOIN outcomes o ON o.action_id=a.id JOIN reports r ON r.id=s.report_id
           WHERE s.kind=?"""
    args = [kind]
    if detail:
        q += " AND s.detail LIKE ?"
        args.append(f"%{detail}%")
    rows = conn.execute(q, args).fetchall()
    if not rows:
        print(f"No past cases for kind={kind} detail={detail or '*'} yet.")
        return
    wins, total, by_action = 0, 0, {}
    for _, _, _, action, worked, note, ts in rows:
        total += 1
        wins += worked
        by_action.setdefault(action, [0, 0, note, ts])
        by_action[action][0] += worked
        by_action[action][1] += 1
    print(f"Recall: {wins}/{total} successful for {kind} {detail or ''}".strip())
    for action, (w, t, note, ts) in sorted(by_action.items(), key=lambda kv: -kv[1][0]):
        print(f"  - [{w}/{t} worked] {action} (last: {ts}; note: {note})")


def rule_matches(rule, data):
    """True if an approved rule's condition matches current measurements."""
    cond = json.loads(rule["cond_json"])
    k = cond.get("kind")
    if k == "heavy_ram":
        return any(p["name"] == cond.get("name") and p["ram_pct"] >= cond.get("min_ram_pct", 10)
                   for p in data["top_ram"])
    if k == "disk_critical":
        return any(d["mount"] == cond.get("mount") and d["pct_free"] < 10 for d in data["disks"])
    if k == "ram_high":
        return data["mem"].percent >= cond.get("min_pct", 85)
    return False


def describe_rule(rule):
    c, a = json.loads(rule["cond_json"]), json.loads(rule["action_json"])
    state = "APPROVED" if rule["approved"] else "proposed"
    return f"rule #{rule['id']} [{state}] when {c} -> do {a} (basis: {rule['basis']})"


def cmd_check(args):
    conn = db(args.db)
    data, sug = collect(args.top)
    report = format_report(data, sug)
    print(report)
    parent = os.path.dirname(os.path.abspath(args.report))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(args.report, "a", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"Saved to: {args.report}")
    mem = data["mem"]
    up = datetime.datetime.now() - data["boot"]
    rid = conn.execute(
        "INSERT INTO reports(ts,ram_pct,ram_used_gb,ram_total_gb,cpu_pct,top_json,disks_json,uptime)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mem.percent,
         round(mem.used / 1e9, 2), round(mem.total / 1e9, 2), data["cpu_total"],
         json.dumps(data["top_ram"]), json.dumps(data["disks"]), str(up))).lastrowid
    for kind, detail, text in sug:
        sid = conn.execute(
            "INSERT INTO suggestions(report_id,kind,detail,text) VALUES(?,?,?,?)",
            (rid, kind, detail, text)).lastrowid
        print(f"  suggestion #{sid} [{kind}/{detail or '-'}]")
    conn.commit()

    # Recall: surface what worked before for anything flagged now.
    for kind, detail, text in sug:
        if kind in ("ok",):
            continue
        print(f"--- recall for [{kind}/{detail or '-'}] ---")
        recall(conn, kind, detail)

    # Stale watch: attach cached weekly audit so uninstall/archive
    # candidates appear on the regular report.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(args.db)), "stale_report.json"),
                  encoding="utf-8") as _f:
            _rep = json.load(_f)
        _age = (datetime.datetime.now() -
                datetime.datetime.strptime(_rep["generated"], "%Y-%m-%d %H:%M:%S")).days
        _apps = sorted(_rep.get("apps", []), key=lambda a: -a.get("gb", 0))[:3]
        _fls = _rep.get("files", [])[:3]
        print(f"--- Stale watch ({_rep['generated']}, {_age}d old) ---")
        for _a in _apps:
            print(f"  unused app: {_a['gb']} GB last={_a['last_run']} {_a['name'][:55]}")
        for _fl in _fls:
            print(f"  untouched file: {_fl['gb']} GB mod={_fl['modified']} {_fl['path']}")
        if _age > 7:
            print("  stale data older than 7d - run `stale` to refresh")
    except (OSError, ValueError, KeyError):
        print("--- Stale watch: no data yet - run `stale` ---")

    # Approved rules: suggest in interactive mode, execute only with --auto.
    for r in conn.execute("SELECT * FROM rules WHERE approved=1").fetchall():
        rule = dict(zip([c[0] for c in conn.execute("SELECT * FROM rules LIMIT 0").description], r))
        if rule_matches(rule, data):
            if args.auto:
                cmd_apply(conn, rule["id"], data)
            else:
                print(f"APPROVED {describe_rule(rule)} -- say 'apply {rule['id']}' to execute.")
    notify(f"RAM {mem.percent}% | CPU {data['cpu_total']}% | " +
           ", ".join(f"{p['name']} {p['ram_pct']}%" for p in data["top_ram"][:2]))
    conn.close()


def cmd_apply(conn, rule_id, data=None):
    """Execute ONE approved rule. Refuses unapproved rules and NEVER_KILL names."""
    row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        print(f"No rule #{rule_id}.")
        return
    rule = dict(zip(["id", "cond_json", "action_json", "approved", "basis"], row))
    if not rule["approved"]:
        print(f"Rule #{rule_id} is NOT approved. Run approve-rule first (your call).")
        return
    cond, act = json.loads(rule["cond_json"]), json.loads(rule["action_json"])
    if act.get("type") == "kill_by_name":
        name = act["name"]
        if name in NEVER_KILL:
            print(f"Refused: {name} is on the never-kill list.")
            return
        killed = []
        for p in psutil.process_iter(["pid", "name", "memory_percent"]):
            try:
                if p.info["name"] == name and (p.info["memory_percent"] or 0) >= cond.get("min_ram_pct", 10):
                    p.terminate()
                    killed.append(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        note = f"auto-killed {name} PIDs {killed}" if killed else f"{name} not found over threshold"
        print(note)
        sid = conn.execute("INSERT INTO suggestions(report_id,kind,detail,text) VALUES(NULL,?,?,?)",
                           ("auto_rule", name, f"Approved rule #{rule_id}: {act}")).lastrowid
        aid = conn.execute("INSERT INTO actions(suggestion_id,action,ts,status) VALUES(?,?,?,?)",
                           (sid, note, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "done")).lastrowid
        conn.execute("INSERT INTO outcomes(action_id,worked,note,ts) VALUES(?,?,?,?)",
                     (aid, 1 if killed else 0, note, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    else:
        print(f"Rule #{rule_id} is suggest-type (no executor): {act}. Act on it yourself, then log with act/outcome.")


def cmd_propose(conn):
    """Group resolved history by (kind, detail, action); propose rules for
    actions with >=1 success. Stored UNAPPROVED — you decide."""
    rows = conn.execute(
        """SELECT s.kind, s.detail, a.action,
                  SUM(o.worked), COUNT(o.worked)
           FROM suggestions s JOIN actions a ON a.suggestion_id=s.id
           JOIN outcomes o ON o.action_id=a.id
           GROUP BY s.kind, s.detail, a.action
           HAVING SUM(o.worked) >= 1 ORDER BY COUNT(o.worked) DESC""").fetchall()
    if not rows:
        print("Not enough resolved history to propose rules yet. Log outcomes first.")
        return
    for kind, detail, action, wins, total in rows:
        al = action.lower()
        # Kill-type rule only for heavy processes; everything else becomes a
        # suggest-type rule (surfaced automatically, never executed alone).
        if kind == "heavy_ram" and ("kill" in al or "terminate" in al) and detail not in NEVER_KILL:
            cond = {"kind": "heavy_ram", "name": detail, "min_ram_pct": 10}
            act = {"type": "kill_by_name", "name": detail}
        elif kind == "disk_critical":
            cond = {"kind": "disk_critical", "mount": detail}
            act = {"type": "suggest", "text": action}
        else:
            cond = {"kind": kind, "detail": detail}
            act = {"type": "suggest", "text": action}
        exists = conn.execute(
            "SELECT id FROM rules WHERE cond_json=? AND action_json=?",
            (json.dumps(cond, sort_keys=True), json.dumps(act, sort_keys=True))).fetchone()
        if exists:
            print(f"already proposed: rule #{exists[0]}")
            continue
        rid = conn.execute(
            "INSERT INTO rules(cond_json,action_json,approved,basis) VALUES(?,?,0,?)",
            (json.dumps(cond, sort_keys=True), json.dumps(act, sort_keys=True),
             f"worked {wins}/{total}: {action}")).lastrowid
        print(f"PROPOSED rule #{rid}: when {cond} -> {act} (worked {wins}/{total})")
    conn.commit()
    print("All proposals are UNAPPROVED. Review with `rules`, approve with `approve-rule ID`.")


def main():
    ap = argparse.ArgumentParser(description="PC Performance Agent: monitor, learn, propose.")
    ap.add_argument("--db", default=os.path.join(os.getcwd(), "performance_history.db"))
    ap.add_argument("--report", default=os.path.join(os.getcwd(), "performance_report.txt"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("init", help="create DB + seed today's session")
    c = sub.add_parser("check", help="monitor once, log, recall, notify")
    c.add_argument("--top", type=int, default=5)
    c.add_argument("--auto", action="store_true", help="execute APPROVED rules (scheduler only)")
    c = sub.add_parser("act", help="log your chosen action")
    c.add_argument("--suggestion", type=int, required=True)
    c.add_argument("--action", required=True)
    c = sub.add_parser("outcome", help="log whether an action worked")
    c.add_argument("--action", type=int, required=True, dest="action_id")
    c.add_argument("--worked", type=int, choices=[0, 1], required=True)
    c.add_argument("--note", default="")
    c.add_argument("--ram-before", type=float, default=None)
    c.add_argument("--ram-after", type=float, default=None)
    c = sub.add_parser("history", help="show past reports/actions/outcomes")
    c.add_argument("--limit", type=int, default=10)
    c = sub.add_parser("recall", help="similar past cases + success rates")
    c.add_argument("--kind", required=True)
    c.add_argument("--detail", default="")
    c = sub.add_parser("propose", help="propose autonomous rules (unapproved)")
    c = sub.add_parser("approve-rule", help="approve a proposed rule (your call)")
    c.add_argument("rule_id", type=int)
    c = sub.add_parser("rules", help="list rules")
    c = sub.add_parser("apply", help="execute one APPROVED rule")
    c.add_argument("rule_id", type=int)
    c = sub.add_parser("stale", help="unused-app + untouched-file audit (weekly job)")
    c.add_argument("--min-mb", type=int, default=100)

    args = ap.parse_args()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if args.cmd == "init":
        conn = db(args.db)
        seed(conn)
        conn.close()
    elif args.cmd == "check":
        cmd_check(args)
    elif args.cmd == "act":
        conn = db(args.db)
        conn.execute("INSERT INTO actions(suggestion_id,action,ts,status) VALUES(?,?,?,?)",
                     (args.suggestion, args.action, now, "done"))
        conn.commit()
        print(f"Logged action for suggestion #{args.suggestion}. Follow up with outcome.")
        conn.close()
    elif args.cmd == "outcome":
        conn = db(args.db)
        conn.execute("INSERT INTO outcomes(action_id,worked,note,ram_before,ram_after,ts)"
                     " VALUES(?,?,?,?,?,?)",
                     (args.action_id, args.worked, args.note, args.ram_before, args.ram_after, now))
        conn.commit()
        print(f"Logged outcome ({'worked' if args.worked else 'did NOT work'}) for action #{args.action_id}.")
        conn.close()
    elif args.cmd == "history":
        conn = db(args.db)
        for r in conn.execute("SELECT id,ts,ram_pct,cpu_pct FROM reports ORDER BY id DESC LIMIT ?",
                              (args.limit,)).fetchall():
            print(f"report #{r[0]} {r[1]} RAM {r[2]}% CPU {r[3]}%")
            for s in conn.execute("SELECT id,kind,detail,text FROM suggestions WHERE report_id=?", (r[0],)):
                print(f"  sug #{s[0]} [{s[1]}/{s[2] or '-'}] {s[3][:100]}")
                for a in conn.execute("SELECT id,action,status FROM actions WHERE suggestion_id=?", (s[0],)):
                    print(f"    act #{a[0]} [{a[2]}] {a[1][:100]}")
                    for o in conn.execute("SELECT worked,note,ram_before,ram_after FROM outcomes WHERE action_id=?", (a[0],)):
                        print(f"      outcome: {'WORKED' if o[0] else 'FAILED'} {o[1]} ({o[2]}->{o[3]})")
        conn.close()
    elif args.cmd == "recall":
        conn = db(args.db)
        recall(conn, args.kind, args.detail)
        conn.close()
    elif args.cmd == "propose":
        conn = db(args.db)
        cmd_propose(conn)
        conn.close()
    elif args.cmd == "approve-rule":
        conn = db(args.db)
        conn.execute("UPDATE rules SET approved=1 WHERE id=?", (args.rule_id,))
        conn.commit()
        print(f"Rule #{args.rule_id} APPROVED. It will now trigger matches (suggest; auto-exec only with --auto).")
        conn.close()
    elif args.cmd == "rules":
        conn = db(args.db)
        for r in conn.execute("SELECT * FROM rules").fetchall():
            print(describe_rule(dict(zip(["id", "cond_json", "action_json", "approved", "basis"], r))))
        conn.close()
    elif args.cmd == "apply":
        conn = db(args.db)
        cmd_apply(conn, args.rule_id)
        conn.close()
    elif args.cmd == "stale":
        import subprocess
        _here = os.path.dirname(os.path.abspath(__file__))
        _out = os.path.join(os.path.dirname(os.path.abspath(args.db)), "stale_report.json")
        subprocess.run([sys.executable, os.path.join(_here, "stale_audit.py"),
                        "--out", _out, "--min-mb", str(args.min_mb)])
        with open(_out, encoding="utf-8") as _f:
            _rep = json.load(_f)
        _apps = sorted(_rep.get("apps", []), key=lambda a: -a.get("gb", 0))
        print(f"Stale watch ({_rep.get('generated')}): {len(_apps)} stale apps, "
              f"{len(_rep.get('files', []))} stale files, "
              f"{len(_rep.get('unverified', []))} unverified")
        for _a in _apps[:5]:
            print(f"  APP {_a['gb']} GB last={_a['last_run']} {_a['name'][:60]}")
        for _fl in _rep.get("files", [])[:5]:
            print(f"  FILE {_fl['gb']} GB mod={_fl['modified']} {_fl['path']}")


if __name__ == "__main__":
    main()
