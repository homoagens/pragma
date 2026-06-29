@echo off
REM ===========================================================================
REM configure.bat - interactive setup of Pragma's .env (Windows).
REM
REM Pipeline: install -> configure -> start.
REM Writes the OpenAI-compatible LLM endpoint settings into .env. Any existing
REM .env is backed up first, and current values are offered as defaults so
REM nothing already configured is overwritten unless you change it.
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"
set "ENV_FILE=.env"

REM --- read current values from .env (if present) -----------------------------
set "CUR_URL="
set "CUR_MODEL="
set "CUR_KEY="
if exist "%ENV_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        if /i "%%A"=="LLM_BASE_URL"  set "CUR_URL=%%B"
        if /i "%%A"=="DEFAULT_MODEL" set "CUR_MODEL=%%B"
        if /i "%%A"=="LLM_API_KEY"   set "CUR_KEY=%%B"
    )
)
if "%CUR_URL%"=="" set "CUR_URL=http://127.0.0.1:8080/v1"

echo Pragma configuration
echo Pragma talks to ONE OpenAI-compatible endpoint: POST {URL}/chat/completions
echo The base URL must end in /v1. Examples:
echo   llama.cpp http://127.0.0.1:8080/v1   LM Studio http://127.0.0.1:1234/v1
echo   Ollama    http://127.0.0.1:11434/v1  vLLM      http://127.0.0.1:8000/v1
echo.

set /p "LLM_BASE_URL=Backend URL (ends in /v1) [%CUR_URL%]: "
if "!LLM_BASE_URL!"=="" set "LLM_BASE_URL=%CUR_URL%"

set /p "DEFAULT_MODEL=Model name (as the server reports it) [%CUR_MODEL%]: "
if "!DEFAULT_MODEL!"=="" set "DEFAULT_MODEL=%CUR_MODEL%"

set /p "LLM_API_KEY=API key (leave empty for local servers) [%CUR_KEY%]: "
if "!LLM_API_KEY!"=="" set "LLM_API_KEY=%CUR_KEY%"

REM --- back up existing .env ---------------------------------------------------
if exist "%ENV_FILE%" (
    copy /y "%ENV_FILE%" "%ENV_FILE%.bak" >nul
    echo Backed up existing .env -^> .env.bak
)

REM --- upsert: keep every other line, replace the three keys -------------------
set "TMP=%ENV_FILE%.tmp"
if exist "%TMP%" del "%TMP%"
if exist "%ENV_FILE%" (
    for /f "usebackq delims=" %%L in ("%ENV_FILE%") do (
        set "LINE=%%L"
        set "SKIP="
        echo !LINE! | findstr /b /i "LLM_BASE_URL=" >nul && set "SKIP=1"
        echo !LINE! | findstr /b /i "DEFAULT_MODEL=" >nul && set "SKIP=1"
        echo !LINE! | findstr /b /i "LLM_API_KEY=" >nul && set "SKIP=1"
        if not defined SKIP echo !LINE!>>"%TMP%"
    )
)
>>"%TMP%" echo LLM_BASE_URL=%LLM_BASE_URL%
>>"%TMP%" echo DEFAULT_MODEL=%DEFAULT_MODEL%
>>"%TMP%" echo LLM_API_KEY=%LLM_API_KEY%
move /y "%TMP%" "%ENV_FILE%" >nul
echo Wrote %ENV_FILE%

REM --- health check: GET {URL}/models -----------------------------------------
echo.
echo Checking %LLM_BASE_URL%/models ...
where curl >nul 2>&1
if errorlevel 1 (
    echo ^(curl not found - skipping health check.^)
    goto :done
)
set "AUTH="
if not "%LLM_API_KEY%"=="" set "AUTH=-H "Authorization: Bearer %LLM_API_KEY%""
for /f %%C in ('curl -s -o NUL -w "%%{http_code}" %AUTH% "%LLM_BASE_URL%/models" 2^>nul') do set "CODE=%%C"
if "%CODE%"=="200" (
    echo OK - endpoint reachable. Run start.bat to launch Pragma.
) else (
    echo WARNING - endpoint returned HTTP %CODE%. Is the server running?
    echo You can still launch Pragma and fix this later ^(Settings in the UI^).
)

:done
endlocal
