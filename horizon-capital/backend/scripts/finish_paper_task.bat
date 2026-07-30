@echo off
REM Windows Scheduled Task entry point for finishing the paper.
REM
REM Exists because the overnight watcher is a bash process started from an
REM interactive session: most of its processes end up orphaned and survive, but
REM one is parented to the terminal and would die when the session closes. A
REM scheduled task depends on nothing that is still running.
REM
REM DEADLINE_EPOCH=0 means "do not wait" -- by the time this fires the arms have
REM either finished or run out of clock, and assembly is idempotent, so running
REM after the watcher already assembled simply rewrites the same blocks.

set "BACKEND=C:\Users\Admin\Documents\Code\Horizon capital\horizon-capital\backend"
set "BASH=C:\Program Files\Git\usr\bin\bash.exe"

cd /d "%BACKEND%"
"%BASH%" -lc "cd '/c/Users/Admin/Documents/Code/Horizon capital/horizon-capital/backend' && DEADLINE_EPOCH=0 bash scripts/finish_paper_overnight.sh" >> "%TEMP%\horizon_paper_finish.log" 2>&1
