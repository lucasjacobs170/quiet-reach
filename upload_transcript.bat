@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ========================================
echo   TRANSCRIPT UPLOAD TOOL
echo ========================================
echo.
echo Step 1: Generating transcript...
python unified_transcript_builder.py --generate
if errorlevel 1 (
echo.
echo ERROR: Transcript generation failed.
echo Make sure transcript_current_session.json exists in this directory.
echo.
pause
exit /b 1
)

echo.
echo Step 2: Preparing to upload...
git add transcripts/
git status transcripts/

echo.
echo Step 3: Committing changes...
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
git commit -m "Transcript upload: %mydate% %mytime%"

echo.
echo Step 4: Pushing to GitHub...
git push origin main
if errorlevel 1 (
echo.
echo Retry push in 3 seconds...
timeout /t 3 /nobreak >nul
git push origin main
if errorlevel 1 (
echo.
echo ERROR: Push failed. Check your internet and git credentials.
echo.
pause
exit /b 1
)
)

echo.
echo ========================================
echo   SUCCESS! Transcript uploaded to GitHub
echo   Location: transcripts/session_latest.json
echo ========================================
echo.
pause
