# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-26

### Added
- Initial release of PC Performance Monitor skill
- `perf_agent.py` — main agent: monitor + learn + propose
  - `check` — RAM/CPU/disks/background apps, top processes, uptime, report, notify, recall
  - `act` / `outcome` — log chosen actions and whether they worked
  - `history` / `recall` — review past cases with success rates
  - `propose` / `approve-rule` / `rules` / `apply` — gated autonomous rule lifecycle
  - `stale` — unused-app (90d) + untouched-file (180d, ≥100MB) audit
  - `watch` — RAM tripwire (alert at 87%, clear at 82%, hysteresis)
  - `init` — DB creation with sample history
- `stale_audit.py` — Uninstall registry + Prefetch + UserAssist evidence; excludes redistributables
- `monitor.py` — lightweight check (no DB, no learning)
- `monitor.ps1` — PowerShell fallback (no Python needed)
- `run/check.bat`, `run/stale.bat`, `run/watch.bat` — Task Scheduler wrappers
- Headless-browser detection (app alive with zero windows)
- Background process ranking (windowless, user-session)
- Disk health flags (OK / LOW <15% / CRITICAL <10%)
- Never-kill list for system processes
- Hourly check + weekly stale + 5-min RAM tripwire schedules
- Field results with measured before/after metrics
- Security audit (SECURITY.md)
- Contributing guide (CONTRIBUTING.md)

### Safety contract
- Report first, never auto-act
- Approvals stay human
- System processes never killed
- No network calls, no telemetry
- No secrets in code or history
- Destructive actions logged with outcomes

## [Unreleased]

### Planned
- Cross-platform support (macOS/Linux)
- GUI dashboard (Tkinter or web-based)
- More rule types (restart_service, clear_cache)
- Unit tests for core functions
- Video tutorial / demo GIF
