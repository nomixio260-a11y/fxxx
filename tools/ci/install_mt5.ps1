# GitHub Actions（Windows）用：MT5 をインストールし、ポータブルモードで MQL5 フォルダを展開する
$ErrorActionPreference = 'Stop'

$url = if ($env:MT5_INSTALLER_URL) { $env:MT5_INSTALLER_URL } else { 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe' }
$setup = Join-Path $env:RUNNER_TEMP 'mt5setup.exe'
Write-Host "Download: $url"
Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing

function Find-Mt5Dir {
  foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if (-not $root) { continue }
    $hit = Get-ChildItem -Path $root -Filter terminal64.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.DirectoryName }
  }
  return $null
}

Write-Host 'Installing MT5 (/auto)...'
Start-Process -FilePath $setup -ArgumentList '/auto' | Out-Null
$deadline = (Get-Date).AddMinutes(15)
$dir = $null
while (-not $dir) {
  if ((Get-Date) -gt $deadline) { throw 'MT5 のインストールがタイムアウトしました' }
  Start-Sleep -Seconds 5
  $dir = Find-Mt5Dir
}
Start-Sleep -Seconds 30
Get-Process terminal64, mt5setup, oanda5setup -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "Installed: $dir"

# ポータブルモードで一度起動して MQL5（標準ライブラリ）を展開
Start-Process -FilePath (Join-Path $dir 'terminal64.exe') -ArgumentList '/portable' | Out-Null
$trade = Join-Path $dir 'MQL5\Include\Trade\Trade.mqh'
$deadline = (Get-Date).AddMinutes(10)
while (-not (Test-Path $trade)) {
  if ((Get-Date) -gt $deadline) { throw 'MQL5 フォルダが展開されませんでした' }
  Start-Sleep -Seconds 5
}
Start-Sleep -Seconds 20
Get-Process terminal64, metaeditor64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

"MT5_DIR=$dir" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
Write-Host 'MQL5 folder ready.'
