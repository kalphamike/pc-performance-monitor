# Contributing to PC Performance Monitor

Thank you for your interest in contributing! This project is a report-first Windows PC monitoring agent with a learning loop and gated autonomy.

## Code of conduct

Be respectful, constructive, and inclusive. This is a beginner-friendly project — many users are not professional developers.

## Getting started

### Prerequisites
- Windows 10 or 11
- Python 3.10+
- Git

### Setup
```powershell
git clone https://github.com/YOUR_USERNAME/pc-performance-monitor.git
cd pc-performance-monitor
pip install psutil plyer
python scripts\perf_agent.py init
python scripts\perf_agent.py check --top 5
```

### Running tests
```powershell
# Syntax check
python -m py_compile scripts\perf_agent.py scripts\stale_audit.py scripts\monitor.py

# Functional check
python scripts\perf_agent.py check --top 5
python scripts\perf_agent.py stale --min-mb 100
python scripts\perf_agent.py history --limit 3
```

## How to contribute

### Bug reports
1. Check existing issues first
2. Include: Windows version, Python version, exact command, error output
3. Include the relevant section from `performance_report.txt` if applicable

### Feature requests
1. Open an issue describing the feature and why it's useful
2. Explain how it fits the safety contract (report first, approvals human)

### Pull requests
1. Fork the repo and create a branch
2. Make your changes
3. Run the tests above
4. Update documentation if needed
5. Submit a PR with a clear description

## Safety contract (must be preserved)

Any contribution must maintain these invariants:

1. **Report first, never auto-act** — no destructive operations without explicit approval
2. **Approvals stay human** — no automatic approval of rules
3. **System processes never killed** — the never-kill list must be preserved
4. **No network calls** — no telemetry, no phone-home, no outbound connections
5. **No secrets** — no credentials, API keys, or tokens in code
6. **Destructive actions logged** — every action must be recorded with outcomes
7. **No shell injection** — use list arguments, not `shell=True`

## Code style

- Python: follow PEP 8, use type hints where practical
- PowerShell: use approved verbs, proper error handling
- Comments: explain *why*, not *what*
- Keep functions focused and under 50 lines when possible

## Project structure

```
pc-performance-monitor/
├── SKILL.md                 # agent instructions
├── README.md                # user documentation
├── LICENSE                  # MIT
├── .gitignore               # excludes runtime data
├── SECURITY.md              # security audit report
├── CONTRIBUTING.md          # this file
├── scripts/
│   ├── perf_agent.py        # main agent: monitor + learn + propose
│   ├── stale_audit.py       # unused-app / untouched-file audit
│   ├── monitor.py           # lightweight check (no DB)
│   └── monitor.ps1          # PowerShell fallback (no Python needed)
└── run/
    ├── check.bat            # hourly task wrapper (edit paths!)
    ├── stale.bat            # weekly task wrapper (edit paths!)
    └── watch.bat            # 5-min RAM tripwire wrapper (edit paths!)
```

## Areas for contribution

- **Cross-platform support**: macOS/Linux monitoring (psutil is cross-platform, but Windows-specific code needs abstraction)
- **GUI dashboard**: A simple Tkinter or web-based dashboard for the SQLite data
- **More rule types**: Beyond kill_by_name and suggest (e.g., restart_service, clear_cache)
- **Better stale detection**: Use Windows Event Log for more accurate run evidence
- **Tests**: Unit tests for the core functions (collect, format_report, rule matching)
- **Documentation**: Translations, video tutorials, blog posts

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
