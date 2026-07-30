@echo off
REM Restore the AC power timeouts that were relaxed so the overnight paper run
REM would not be suspended mid-flight.
REM
REM standby-timeout-ac 600 is the value that was actually read back from this
REM machine before the change (10 minutes).
REM
REM disk-timeout-ac 1200 is the Windows default (20 minutes), NOT a recorded
REM value -- the original was not captured before it was overwritten. If the
REM machine had a non-default disk timeout, set it again by hand.
REM
REM hibernate-timeout-ac is deliberately left at 0. This machine reports
REM "Standby (S0 Low Power Idle)", where classic hibernate-after-idle is not
REM the mechanism in use, and 0 is the usual setting on such systems.
REM
REM Battery timeouts were never touched.

powercfg /change standby-timeout-ac 600
powercfg /change disk-timeout-ac 1200

echo [%DATE% %TIME%] restored: standby-timeout-ac=600 disk-timeout-ac=1200 >> "%TEMP%\horizon_power_restore.log"
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE >> "%TEMP%\horizon_power_restore.log" 2>&1
