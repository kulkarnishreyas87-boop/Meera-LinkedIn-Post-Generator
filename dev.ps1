# Windows equivalent of `make dev`: API + bot on :8000, Vite dashboard on :5173.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "No .venv found. See README > Setup." }
if (-not (Test-Path (Join-Path $root ".env"))) { Write-Warning "No .env found - copy .env.example to .env and fill it in." }

$api = Start-Process -PassThru -NoNewWindow -WorkingDirectory $root -FilePath $py `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload", "--reload-dir", "app"
Write-Host "API + bot  -> http://127.0.0.1:8000"
Write-Host "Dashboard  -> http://localhost:5173   (Ctrl+C to stop both)"
try {
  Push-Location (Join-Path $root "web")
  npm run dev
} finally {
  Pop-Location
  if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
