param([int]$Port = 3000)

$ErrorActionPreference = "Stop"
$env:PORT = [string]$Port

Write-Host "Starting NeteaseCloudMusicApi on http://localhost:$Port"
Write-Host "If the backend runs on Windows, prefer NETEASE_API_BASE_URL=http://localhost:$Port."
Write-Host "If the backend runs in WSL, try NETEASE_API_BASE_URL=http://127.0.0.1:$Port first."
Write-Host "If neither localhost nor 127.0.0.1 works in WSL, switch to the appropriate bridge address."
Write-Host "Press Ctrl+C to stop the NetEase API service."

npx.cmd -y NeteaseCloudMusicApi@latest
