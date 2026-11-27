# GitHub Actions（Windows）用：MT5 をインストールし、ポータブルモードで MQL5 フォルダを展開する
# 配布元（MetaQuotes の CDN）が一時的に落ちていることがある（2026年11月22日に4回続けて失敗し、デモ口座の運用が止まった）。
# そのため、ダウンロードとインストールは、時間を空けて何度かやり直す。
$ErrorActionPreference = 'Stop'

$url = if ($env:MT5_INSTALLER_URL) { $env:MT5_INSTALLER_URL } else { 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe' }
$setup = Join-Path $env:RUNNER_TEMP 'mt5setup.exe'

# インストーラーをダウンロードする（最大8回、待ち時間を伸ばしながら。合計で約30〜40分まで）
function Get-Installer {
  for ($i = 1; $i -le 8; $i++) {
    try {
      Write-Host "Download ($i): $url"
      Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing -TimeoutSec 120
      if ((Test-Path $setup) -and ((Get-Item $setup).Length -gt 100000)) { return $true }
      Write-Host 'ダウンロードしたファイルが小さすぎます'
    } catch {
      Write-Host "ダウンロードに失敗しました: $($_.Exception.Message)"
    }
    if ($i -lt 8) {
      $wait = [Math]::Min(60 * $i, 300)
      Write-Host "$wait 秒待って、やり直します"
      Start-Sleep -Seconds $wait
    }
  }
  return $false
}

function Find-Mt5Dir {
  foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if (-not $root) { continue }
    $hit = Get-ChildItem -Path $root -Filter terminal64.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.DirectoryName }
  }
  return $null
}

# インストーラーを1回動かし、terminal64.exe ができるまで最大15分待つ（できなければ $null）
function Install-Once {
  Start-Process -FilePath $setup -ArgumentList '/auto' | Out-Null
  $deadline = (Get-Date).AddMinutes(15)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $d = Find-Mt5Dir
    if ($d) { return $d }
  }
  return $null
}

if (-not (Get-Installer)) { throw 'MT5 のインストーラーをダウンロードできませんでした（配布元が落ちている可能性があります）' }

$dir = $null
for ($k = 1; ($k -le 2) -and (-not $dir); $k++) {
  Write-Host "Installing MT5 (/auto)... ($k)"
  $dir = Install-Once
  if (-not $dir) {
    Write-Host 'インストールが時間内に終わりませんでした'
    Get-Process mt5setup, oanda5setup -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 60
  }
}
if (-not $dir) { throw 'MT5 のインストールがタイムアウトしました' }
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
