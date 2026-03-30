# Travel Planner Memory POC — Launcher
# Usage: .\start.ps1          (just start)
#        .\start.ps1 --seed   (seed demo data first)

$root = $PSScriptRoot
Push-Location $root

Write-Host "`n🌍 Travel Planner Memory POC" -ForegroundColor Cyan

# Kill any existing process on port 8502
$pids = netstat -ano | Select-String ":8502\s.*LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Sort-Object -Unique
foreach ($pid in $pids) {
    Write-Host "  Killing PID $pid on port 8502..." -ForegroundColor Yellow
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

# Init DB schema
Write-Host "  Initialising DB..." -ForegroundColor Gray
python -c "from db import init_db; init_db()"

# Seed if requested
if ($args -contains "--seed") {
    Write-Host "  Seeding demo data..." -ForegroundColor Gray
    python -c "from db import seed_demo_data; seed_demo_data()"
}

# Start Streamlit
Write-Host "  Starting Streamlit on port 8502...`n" -ForegroundColor Green
$env:PYTHONPATH = "."
streamlit run streamlit_app.py --server.port 8502 --server.headless true

Pop-Location
