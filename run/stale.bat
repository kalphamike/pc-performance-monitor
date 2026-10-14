@echo off
REM Weekly stale audit. EDIT the two paths below, then:
REM   schtasks /Create /TN "PC Stale Audit" /TR "<this-file>" /SC WEEKLY /D SUN /ST 04:00 /F
C:\Python314\pythonw.exe "C:\path\to\pc-performance-monitor\scripts\stale_audit.py" --out "C:\path\to\working\stale_report.json" --min-mb 100
