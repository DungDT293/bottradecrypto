$ErrorActionPreference = 'Stop'

$installer = Get-ChildItem -Path 'desktop/src-tauri/target/release/bundle/nsis' -Filter '*.exe' | Select-Object -First 1
if (-not $installer) { throw 'NSIS installer not found' }

$installRoot = Join-Path $env:RUNNER_TEMP 'tbce-install'
New-Item -ItemType Directory -Force $installRoot | Out-Null

# Silent install into runner-owned location. Installer must not receive secrets.
Start-Process -FilePath $installer.FullName -ArgumentList '/S', "/D=$installRoot" -Wait -NoNewWindow
$app = Get-ChildItem -Path $installRoot -Filter '*.exe' -Recurse | Where-Object { $_.Name -notmatch 'unins' } | Select-Object -First 1
if (-not $app) { throw 'Installed application executable not found' }

$env:TBCE_ALLOW_BROWSER_HANDSHAKE = '0'
$process = Start-Process -FilePath $app.FullName -WorkingDirectory $installRoot -PassThru
try {
  $appData = Join-Path $env:APPDATA 'telegram_binance_signal_executor'
  $config = Join-Path $appData 'config.yaml'
  $deadline = (Get-Date).AddSeconds(30)
  while (-not (Test-Path $config) -and (Get-Date) -lt $deadline) {
    if ($process.HasExited) { throw "Application exited during startup: $($process.ExitCode)" }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Path $config)) {
    Write-Host "Install root: $installRoot"
    Write-Host "AppData root: $appData"
    Get-ChildItem -Path $installRoot -Recurse -ErrorAction SilentlyContinue | Select-Object FullName
    throw 'Runtime config was not created'
  }
  if ($process.HasExited) { throw "Application exited during startup: $($process.ExitCode)" }
  $configText = Get-Content -Raw $config
  if ($configText -match 'mode:\s*LIVE|live_trading_enabled:\s*true|BINANCE_.*(KEY|SECRET)=\S+') {
    throw 'Unsafe LIVE mode or credential material found in installed runtime config'
  }
  if ($configText -notmatch 'mode:\s*READ_ONLY') { throw 'Installed runtime is not READ_ONLY by default' }
} finally {
  if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

$uninstaller = Get-ChildItem -Path $installRoot -Filter 'unins*.exe' -Recurse | Select-Object -First 1
if ($uninstaller) { Start-Process -FilePath $uninstaller.FullName -ArgumentList '/VERYSILENT', '/NORESTART' -Wait -NoNewWindow }
Write-Host 'Windows installer smoke passed'
