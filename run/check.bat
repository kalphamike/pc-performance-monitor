@echo off
REM 4-hourly PC Performance Agent run. EDIT the three paths below, then:
REM   schtasks /Create /TN "PC Performance Monitor Py" /TR "<this-file>" /SC HOURLY /MO 4 /F
REM No --auto here: approved rules are only suggested, never executed headlessly.
C:\Python314\pythonw.exe "C:\path\to\pc-performance-monitor\scripts\perf_agent.py" --db "C:\path\to\working\performance_history.db" --report "C:\path\to\working\performance_report.txt" check --top 5
