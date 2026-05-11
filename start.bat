@echo off
REM Quant Lab launcher — avvia la dashboard Streamlit.
REM Doppio-click su questo file per aprire il sistema nel browser.

setlocal
cd /d "%~dp0"

REM ---- venv activation (optional) ------------------------------------
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [info] .venv\ non trovato — uso il Python di sistema.
    echo [info] Se vuoi un venv dedicato:  python -m venv .venv  e  pip install -r requirements.txt
)

REM ---- preflight: required deps --------------------------------------
python -c "import streamlit, streamlit_autorefresh" 2>NUL
if errorlevel 1 (
    echo.
    echo [warning] streamlit o streamlit_autorefresh mancanti.
    echo Sto installando i pacchetti minimi…
    pip install streamlit streamlit-autorefresh plotly
    if errorlevel 1 (
        echo [error] Installazione fallita. Aggiusta manualmente e ritenta.
        pause
        exit /b 1
    )
)

REM ---- launch --------------------------------------------------------
echo.
echo ============================================
echo   Quant Lab — Dashboard
echo   URL:  http://localhost:8501
echo   CTRL+C per arrestare
echo ============================================
echo.

start "" "http://localhost:8501"
python -m streamlit run ui/main.py --server.port 8501 --server.headless=false

pause
