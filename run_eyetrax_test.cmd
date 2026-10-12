@echo off
REM ======================================================================
REM  run_eyetrax_test.cmd
REM  Measure EyeTrax gaze accuracy on this machine.
REM
REM  This file is intentionally ASCII-only. Batch files are parsed with the
REM  console code page, so non-ASCII text gets mangled depending on the
REM  system locale (this was a real bug: the Chinese comments turned into
REM  garbage and the commands got split apart).
REM
REM  ---------------------------------------------------------------------
REM  WHAT YOU NEED FIRST
REM  ---------------------------------------------------------------------
REM  This script cross-checks our own gaze model against EyeTrax.
REM  It does NOT run out of the box, because two things are not in the repo:
REM
REM    1. Python packages: mediapipe, opencv-python, numpy, matplotlib
REM       pip install mediapipe opencv-python numpy matplotlib
REM
REM    2. The MediaPipe face landmarker model (about 3.5 MB), which we
REM       deliberately did not commit (vendor/ is 30 MB of binaries).
REM       Download it and put it at:
REM           vendor\face_landmarker.task
REM       Get it from the MediaPipe model page:
REM           https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker
REM
REM  Usage:
REM    run_eyetrax_test.cmd             default 1280x720
REM    run_eyetrax_test.cmd 640 480     compare at 640x480
REM ======================================================================

REM %~dp0 is the folder this script sits in (with a trailing backslash).
REM Using it instead of an absolute path means the repo can live anywhere.
set "HERE=%~dp0"

REM Use whichever python is on PATH. If you need a specific one, replace this.
set "PY312=python"
set "PYTHONPATH=%HERE%.pylibs"
set "MPLCONFIGDIR=%TEMP%\mplcache"
set "PYTHONIOENCODING=utf-8"
set "EYETRAX_FACE_LANDMARKER_MODEL=%HERE%vendor\face_landmarker.task"

if not exist "%EYETRAX_FACE_LANDMARKER_MODEL%" (
  echo.
  echo  ERROR: the face landmarker model is missing.
  echo.
  echo  Expected at:
  echo    %EYETRAX_FACE_LANDMARKER_MODEL%
  echo.
  echo  It is not in the repo on purpose ^(30 MB of binaries^).
  echo  See the header of this file for where to get it.
  echo.
  pause
  exit /b 1
)

set "W=%~1"
set "H=%~2"
if "%W%"=="" set "W=1280"
if "%H%"=="" set "H=720"

echo ============================================================
echo  EyeTrax gaze accuracy test   resolution %W% x %H%
echo ============================================================
echo.
echo  9 yellow dots will appear fullscreen, one at a time.
echo  Look at each dot for about 1.8 seconds.
echo  Keep your head still during the test.
echo.
echo  (Make sure no browser tab is using the camera.)
echo.
pause

"%PY312%" "%HERE%tools\gaze-research\archive\eyetrax_accuracy_test.py" --run --width %W% --height %H%

echo.
echo ============================================================
echo  Done. Result written to eyetrax_result.json
echo ============================================================
pause
