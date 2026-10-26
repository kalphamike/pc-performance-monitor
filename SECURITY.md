# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ |

## Reporting a vulnerability

If you find a security issue in this project, please **do not** open a public issue.

Instead, contact the maintainer privately via GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability).

## Security audit

A full security audit was performed before the initial release. Key findings:

- **No network calls** — zero telemetry, no phone-home, no outbound connections
- **No secrets** — no passwords, API keys, or credentials in code or history
- **No destructive auto-actions** — all kills require human approval; system processes are on a never-kill list
- **No code injection** — subprocess uses list (not `shell=True`), SQL uses parameterized queries
- **No path traversal** — all file operations use explicit, user-provided paths
- **Dependencies**: psutil 7.2.2 + plyer 2.1.0 (both well-known PyPI packages)

## Safety contract

This tool is designed to be **report-first and approval-gated**:

1. **Monitor** — reads system metrics (RAM, CPU, processes, disks)
2. **Report** — writes timestamped reports and SQLite logs
3. **Recall** — surfaces past fixes with success rates
4. **Act** — logs your chosen action (you decide)
5. **Outcome** — logs whether it worked (you report)
6. **Propose** — derives rule candidates (stored unapproved, inert)
7. **Approve** — you explicitly approve each rule
8. **Apply** — executes one approved rule (logged with outcome)

### What it never does
- Never deletes, uninstalls, or modifies files
- Never modifies the registry (documents how, but doesn't execute)
- Never makes network calls
- Never kills system processes (hardcoded never-kill list)
- Never acts without approval
- Never stores secrets or credentials

### Never-kill list
`System`, `Registry`, `smss.exe`, `csrss.exe`, `wininit.exe`, `services.exe`, `lsass.exe`, `dwm.exe`, `explorer.exe`, `System Idle Process`

These can never be killed, even by approved auto-rules.

## Dependency policy

- Only well-known PyPI packages with millions of downloads
- No third-party or obscure dependencies
- All other imports are Python stdlib
- Dependencies are pinned to specific versions in the audit

## Responsible disclosure

We take security seriously. If you discover a vulnerability, please report it privately. We will acknowledge within 48 hours and aim to fix within 7 days.
