# Expose the local stack on a public HTTPS URL (for PayPal webhooks and Twilio) with a Cloudflare quick tunnel.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1
# Then:   put the printed URL + "/api" in .env as APP_URL, run `docker compose up -d api`,
#         and register <URL>/api/webhooks/paypal (PayPal) and <URL>/api/voice/twilio/incoming (Twilio).
$ErrorActionPreference = "Stop"
$exe = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Downloading cloudflared (official GitHub release)..."
    Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/download/2025.8.1/cloudflared-windows-amd64.exe" -OutFile $exe
}
Write-Host "Starting tunnel to Kong on http://localhost:8090 ... (Ctrl+C to stop)"
& $exe tunnel --no-autoupdate --url http://localhost:8090
