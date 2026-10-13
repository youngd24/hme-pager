@ECHO OFF
REM Start Capcoder. Usage: capcoder.cmd [CAPCODE]
REM With no capcode, defaults to 870008 (base 087, pager 1).

SETLOCAL
SET "CAPCODE=%~1"
IF "%CAPCODE%"=="" SET "CAPCODE=870008"

REM Run from the repo folder so "python -m capcoder" finds the package,
REM wherever this file is started from.
PUSHD "%~dp0"

ECHO STARTING CAPCODER AS CAPCODE %CAPCODE%

python -m capcoder --capcode %CAPCODE%

POPD
ENDLOCAL
