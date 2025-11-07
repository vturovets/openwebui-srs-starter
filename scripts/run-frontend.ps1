# Param(
#   [string]$Port = "5173",
#   [string]$ApiBase = "http://127.0.0.1:8000"
# )
#
# $ErrorActionPreference = "Stop"
#
# # --- Resolve npm on Windows/Pwsh ---
# # Prefer npm.cmd on Windows; fall back to npm for other shells.
# $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)?.Source
# if (-not $npmCmd) { $npmCmd = (Get-Command npm -ErrorAction SilentlyContinue)?.Source }
# if (-not $npmCmd) { throw "npm not found. Install Node.js (which includes npm) and ensure it's on PATH." }
#
# # --- Move to frontend ---
# Push-Location (Join-Path $PSScriptRoot "..\frontend")
#
# # Install deps if missing
# if (-not (Test-Path node_modules)) {
#   Write-Host "node_modules not found → running 'npm ci'..."
#   & $npmCmd ci
# }
#
# # Env for Vite to read
# $env:VITE_API_BASE = $ApiBase
#
# # URL we intend to open
# $url = "http://localhost:$Port/"
#
# Write-Host "Starting Vite on $url (will auto-open a new browser tab)..."
#
# # TIP: keep the process in THIS terminal so logs appear in IntelliJ Run window.
# # Use Vite's --open to pop the tab. Also set --port explicitly (Vite ignores PORT env).
# & $npmCmd run dev -- --port $Port --strictPort --host --open
#
# # Control returns here only when Vite stops.
# Pop-Location


Param(
  [string]$Port = "5173",
  [string]$ApiBase = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

# Go to frontend folder
Push-Location "$PSScriptRoot\..\frontend"

# Install deps if node_modules missing
if (-not (Test-Path node_modules)) { npm ci }

# Optional env vars for Vite
$env:VITE_API_BASE = $ApiBase
$env:PORT = $Port

npm run dev -- --port $Port --strictPort --host --open

Pop-Location
