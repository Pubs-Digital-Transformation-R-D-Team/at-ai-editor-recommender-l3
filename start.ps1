# ── L3 POC Launcher ──────────────────────────────────────────────────────────
# Starts LangGraph (8000), Strands COI (8001), and Streamlit UI (8501)
# Usage: Right-click → "Run with PowerShell"  OR  .\start.ps1

$root = $PSScriptRoot

# Kill anything on the 3 ports
foreach ($port in @(8000, 8001, 8501)) {
    netstat -ano | findstr ":$port " | findstr "LISTENING" |
        ForEach-Object { Stop-Process -Id ($_ -split '\s+')[-1] -Force -EA SilentlyContinue }
}

Write-Host "`n Starting LangGraph backend  (port 8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$root'; `$env:PYTHONPATH='.'; `$env:MOCK_COI='true'; `$env:MOCK_REACT='true'; python langgraph_service/callback_server.py"

Start-Sleep -Seconds 2

Write-Host " Starting Strands COI backend (port 8001)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$root'; `$env:PYTHONPATH='.'; `$env:MOCK_COI='true'; python strands_service/server.py"

Start-Sleep -Seconds 3

Write-Host " Starting Streamlit UI        (port 8501)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$root'; streamlit run streamlit_app.py --server.port 8501"

Start-Sleep -Seconds 4

Write-Host "`n All services started. Opening browser..." -ForegroundColor Green
Start-Process "http://localhost:8501"
