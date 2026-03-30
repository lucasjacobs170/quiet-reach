@echo off
echo Generating transcript...
python unified_transcript_builder.py --generate --output transcripts/session_latest.json
if errorlevel 1 (
    echo.
    echo ERROR: Transcript generation failed. Make sure transcript_current_session.json exists.
    pause
    exit /b 1
)

echo.
echo Committing to Git...
git add -f transcripts/
git status --short transcripts/
git commit -m "Transcript update: %date% %time%"
if errorlevel 1 (
    echo.
    echo NOTE: Nothing new to commit, or git commit failed.
)

echo.
echo Pushing to GitHub...
git push
if errorlevel 1 (
    echo.
    echo Push failed. Retrying in 5 seconds...
    timeout /t 5 /nobreak >nul
    git push
    if errorlevel 1 (
        echo.
        echo ERROR: Push failed after retry. Check your git credentials and internet connection.
        pause
        exit /b 1
    )
)

echo.
echo Done!
echo Transcript uploaded to: transcripts/session_latest.json
pause
