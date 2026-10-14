# PC Performance Monitor

A report-first Windows PC monitoring agent: it watches RAM, CPU, disks, background apps, and software staleness — logs everything to SQLite, learns which fixes worked, and proposes autonomous rules that **only you can approve**.

Built for [OpenCode](https://opencode.ai) as a skill (`SKILL.md`), with standalone scripts that also run without any agent.

## How it works

```
every 4h:  check  →  report  →  notify  →  recall past fixes
                                              ↓
you:       act  →  outcome (worked? yes/no)
                                              ↓
agent:     propose rules (inert)  →  you approve  →  apply (logged)
```

- **Monitor** (`check`): RAM/CPU totals, top processes, windowless background ranking, headless-browser flag (app alive with zero windows), disk health + free space, uptime.
- **Stale watch** (`stale`, weekly): apps not run in 90+ days (Uninstall registry + Prefetch/UserAssist run evidence) and files ≥100 MB untouched in 180+ days — uninstall/archive candidates with sizes.
- **Learn** (`act`/`outcome`/`history`/`recall`): every report, suggestion, chosen action, and result lands in `performance_history.db` with success rates.
- **Autonomy, gated**: `propose` derives rules from fixes that worked. Proposals are inert until `approve-rule`. Even approved rules only suggest — headless execution needs an explicit `--auto` opt-in. Kill-type rules refuse system processes via a hardcoded never-kill list.

## Requirements

- Windows 10/11, Python 3.10+
- `pip install psutil plyer`

## Quickstart

```powershell
cd pc-performance-monitor
pip install psutil plyer

# first run: creates performance_history.db with sample history
python scripts\perf_agent.py init

# monitor once (appends performance_report.txt, logs to DB, notifies)
python scripts\perf_agent.py check --top 5

# log what you did about suggestion #N, then whether it worked
python scripts\perf_agent.py act --suggestion N --action "killed orphaned cmd PID 1234"
python scripts\perf_agent.py outcome --action 1 --worked 1 --note "RAM 66->63%" --ram-before 66 --ram-after 63

# look up similar past cases, review history, propose rules
python scripts\perf_agent.py recall --kind heavy_ram --detail cmd.exe
python scripts\perf_agent.py history --limit 5
python scripts\perf_agent.py propose
python scripts\perf_agent.py rules
```

## Scheduling (Task Scheduler)

Every 4 hours (report + log + suggest; never executes):

```powershell
schtasks /Create /TN "PC Performance Monitor Py" /TR "<repo>\run\check.bat" /SC HOURLY /MO 4 /F
```

Weekly stale audit, Sundays 04:00:

```powershell
schtasks /Create /TN "PC Stale Audit" /TR "<repo>\run\stale.bat" /SC WEEKLY /D SUN /ST 04:00 /F
```

> `schtasks /TR` is limited to 261 characters — use the `.bat` wrappers in `run\`, never inline the full command. See `run\check.bat` as a template (edit the Python and working-dir paths).

Remove any time:

```powershell
schtasks /Delete /TN "PC Performance Monitor Py" /F
schtasks /Delete /TN "PC Stale Audit" /F
```

## Command reference

| Command | Purpose |
|---|---|
| `init` | Create DB (+ sample history on empty DB) |
| `check [--top N] [--auto]` | Monitor, log, recall, notify |
| `act --suggestion ID --action "..."` | Log your chosen action |
| `outcome --action ID --worked 0\|1 [--note ...]` | Log the result (the learning signal) |
| `history [--limit N]` | Past reports → suggestions → actions → outcomes |
| `recall --kind K [--detail T]` | Similar cases + success rates |
| `propose` | Derive rule candidates (stored unapproved) |
| `approve-rule ID` | Approve (human only) |
| `rules` | List rules + approval state |
| `apply ID` | Execute one approved rule (logged) |
| `stale [--min-mb 100]` | Unused-app / untouched-file audit |

Suggestion kinds: `heavy_ram`, `cpu_hog`, `headless_app`, `disk_critical`, `disk_low`, `ram_high`, `ok`.

## Project structure

```
pc-performance-monitor/
├── SKILL.md                 # agent instructions (OpenCode skill)
├── README.md
├── LICENSE
├── .gitignore
├── scripts/
│   ├── perf_agent.py        # main agent: monitor + learn + propose
│   ├── stale_audit.py       # unused-app / untouched-file audit
│   ├── monitor.py           # lightweight check (no DB)
│   └── monitor.ps1          # PowerShell fallback (no Python needed)
└── run/
    ├── check.bat            # 4-hourly task wrapper (edit paths!)
    └── stale.bat            # weekly task wrapper (edit paths!)
```

Runtime files (`performance_report.txt`, `performance_history.db`, `stale_report.json`) are created in your working directory and git-ignored — your process history never lands in the repo.

## Notes & limits

- File "untouched" uses last-write time: Windows disables last-access tracking by default, so opens can't be measured.
- "No run evidence" for an app means unverified (portable/store apps leave weak traces) — confirm before removing. Redistributables and security dependencies are never suggested.
- Tested on Windows 11 + Python 3.14. PowerShell edition included for Python-less machines.

## Contributing

Issues and PRs welcome. Please keep the safety contract: report first, approvals stay human, destructive actions stay logged with outcomes.

## License

MIT — see [LICENSE](LICENSE).
