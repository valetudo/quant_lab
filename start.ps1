# Quant Lab launcher (PowerShell) — avvia la dashboard Streamlit.
# Usage:  Right-click → Run with PowerShell, oppure  .\start.ps1
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

# ---- venv activation (optional) ------------------------------------
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & ".venv\Scripts\Activate.ps1"
} else {
    Write-Host "[info] .venv\ non trovato — uso il Python di sistema." -ForegroundColor Yellow
    Write-Host "[info] Se vuoi un venv dedicato:  python -m venv .venv  e  pip install -r requirements.txt"
}

# ---- preflight: required deps --------------------------------------
python -c "import streamlit, streamlit_autorefresh" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[warning] streamlit o streamlit_autorefresh mancanti." -ForegroundColor Yellow
    Write-Host "Sto installando i pacchetti minimi..."
    pip install streamlit streamlit-autorefresh plotly
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Installazione fallita. Aggiusta manualmente e ritenta."
        Read-Host -Prompt "Premi Invio per chiudere"
        exit 1
    }
}

# ---- launch --------------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Quant Lab — Dashboard" -ForegroundColor Cyan
Write-Host "  URL:  http://localhost:8501" -ForegroundColor Cyan
Write-Host "  CTRL+C per arrestare" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Start-Process "http://localhost:8501"
python -m streamlit run ui/main.py --server.port 8501 --server.headless=$false
