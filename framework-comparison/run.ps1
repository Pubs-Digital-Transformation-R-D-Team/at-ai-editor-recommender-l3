<#
.SYNOPSIS
    Launch the Strands vs LangGraph Framework Comparison Streamlit app.

.DESCRIPTION
    Finds an available port (default 8502), kills any stale process on it,
    and starts streamlit_app.py.

.EXAMPLE
    .\run.ps1            # default port 8502
    .\run.ps1 -Port 8510 # custom port
#>

param(
    [int]$Port = 8502
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=== Framework Comparison: Strands vs LangGraph ===" -ForegroundColor Cyan
Write-Host ""

# ── Free the port if something is already listening ──────────────────────────
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
    foreach ($conn in $existing) {
        Write-Host "  Killing stale process PID $($conn.OwningProcess) on port $Port..." -ForegroundColor Yellow
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

# ── Install deps if needed ───────────────────────────────────────────────────
$missing = @()
foreach ($pkg in @("streamlit", "pandas")) {
    python -c "import $pkg" 2>$null
    if ($LASTEXITCODE -ne 0) { $missing += $pkg }
}
if ($missing.Count -gt 0) {
    Write-Host "  Installing missing packages: $($missing -join ', ')..." -ForegroundColor Yellow
    pip install $missing --quiet
}

# ── Launch ───────────────────────────────────────────────────────────────────
Write-Host "  Starting on http://localhost:$Port" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

streamlit run streamlit_app.py --server.port $Port --server.headless true
