@echo off
REM Windows wrapper only - all startup/orchestration logic lives in run_meetnote.py.
REM Delegates verbatim; do not add startup logic here.
python "%~dp0run_meetnote.py" %*
