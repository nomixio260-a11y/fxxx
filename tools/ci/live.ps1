# GitHub Actions（Windows）用：OANDA デモ口座で EA を実際に動かす（フォワードテスト）
# 必要なシークレット: MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
# 環境変数:
#   LIVE_MINUTES  この回で動かす最大の分数（既定 330）
#   LIVE_PRESET   使うプリセット（MQL5\Presets のファイル名、既定 AMS_Calendar_Portfolio.set）
#   LIVE_SYMBOL   EA を付けるチャートの銘柄（既定 USDJPY）
$ErrorActionPreference = 'Stop'
$dir    = $env:MT5_DIR
$repo   = $env:GITHUB_WORKSPACE
$runMin = if ($env:LIVE_MINUTES) { [int]$env:LIVE_MINUTES } else { 330 }
$preset = if ($env:LIVE_PRESET) { $env:LIVE_PRESET } else { 'AMS_Calendar_Portfolio.set' }
$symbol = if ($env:LIVE_SYMBOL) { $env:LIVE_SYMBOL } else { 'USDJPY' }
$common = Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
$outDir = Join-Path $repo 'reports\live'
New-Item -ItemType Directory -Force -Path "$dir\MQL5\Presets", $common, $outDir | Out-Null
Copy-Item "$repo\MQL5\Presets\*.set" "$dir\MQL5\Presets\" -Force

# 取引の時間帯に入れ替わりの切れ目が来ないように、終わる時刻を決める（UTC）。
#   東京の朝（日本時間 9:00〜12:10 = UTC 0:00〜3:10）と、C4（日本時間 21:35〜24:10 = UTC 12:35〜15:10）
$start = (Get-Date).ToUniversalTime()
$end   = $start.AddMinutes($runMin)
$windows = @(@(0, 0, 3, 10), @(12, 35, 15, 10))
function In-Window([datetime]$t) {
  foreach ($w in $windows) {
    $ws = $t.Date.AddHours($w[0]).AddMinutes($w[1]); $we = $t.Date.AddHours($w[2]).AddMinutes($w[3])
    if ($t -ge $ws.AddMinutes(-20) -and $t -lt $we) { return $ws.AddMinutes(-20) }   # 次の回の準備（約15分）も見込む
  }
  return $null
}
$ws = In-Window $end
if ($ws) {
  if (($ws - $start).TotalMinutes -ge 30) { $end = $ws }                 # 時間帯の前に終える
  else { $end = $start.AddMinutes(350) }                                 # 時間帯をまたいで最後まで動かす
}
Write-Host "開始 $($start.ToString('yyyy-MM-dd HH:mm')) UTC → 終了予定 $($end.ToString('yyyy-MM-dd HH:mm')) UTC（プリセット $preset）"
"LIVE_END_UTC=$($end.ToString('o'))" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

$ini = @"
[Common]
Login=$($env:MT5_LOGIN)
Password=$($env:MT5_PASSWORD)
Server=$($env:MT5_SERVER)
KeepPrivate=1
NewsEnable=0

[Experts]
AllowLiveTrading=1
AllowDllImport=0
Enabled=1
Account=0
Profile=0

[StartUp]
Expert=AdaptiveMultiStrategyEA
ExpertParameters=$preset
Symbol=$symbol
Period=M5
"@
$conf = Join-Path $dir 'ams_live.ini'
$ini | Out-File -FilePath $conf -Encoding ascii

$script:shown = @{}
function Show-NewLines([string]$pattern, [string]$tag) {
  $found = @()
  Get-ChildItem $pattern -ErrorAction SilentlyContinue | ForEach-Object {
    $lines = @(Get-Content $_.FullName -Encoding Unicode -ErrorAction SilentlyContinue)
    $s = if ($script:shown.ContainsKey($_.FullName)) { $script:shown[$_.FullName] } else { 0 }
    for ($i = $s; $i -lt $lines.Count; $i++) {
      # ログイン成功の確認は、口座番号を隠す前に行う
      if ($lines[$i] -match 'authorized on') { $script:authorized = $true }
      # 口座番号を含む行は表示しない（ログは公開されるため）
      if ($env:MT5_LOGIN -and $lines[$i].Contains($env:MT5_LOGIN)) { continue }
      Write-Host "[$tag] $($lines[$i])"; $found += $lines[$i]
    }
    $script:shown[$_.FullName] = $lines.Count
  }
  return $found
}

$eaLines = @()
try {
  $p = Start-Process -FilePath (Join-Path $dir 'terminal64.exe') -ArgumentList '/portable', "/config:`"$conf`"" -PassThru
  Start-Sleep -Seconds 90
  Remove-Item $conf -ErrorAction SilentlyContinue   # パスワードを含むので、起動したらすぐ消す
  $script:authorized = $false
  while ((Get-Date).ToUniversalTime() -lt $end) {
    if ($p.HasExited) { Write-Host 'ターミナルが終了しました'; break }
    $new = @(Show-NewLines "$dir\logs\*.log" 'terminal')
    $ea  = @(Show-NewLines "$dir\MQL5\Logs\*.log" 'ea')
    $eaLines += $ea | Where-Object { $_ -match '\[AMS\]' }
    if ($new | Where-Object { $_ -match 'authorization on .* failed' }) { Write-Host 'NG: ログインに失敗しました'; break }
    Start-Sleep -Seconds 60
  }
  if ($script:authorized) { Write-Host 'ログインできました' } else { Write-Host '注意：ログインの成功をログで確認できませんでした' }
} finally {
  Remove-Item $conf -ErrorAction SilentlyContinue
  # 正しい手順で終了させ、EA の OnDeinit（状態の保存・記録の書き出し）を動かす
  Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }
  $deadline = (Get-Date).AddSeconds(120)
  while ((Get-Process terminal64 -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 5 }
  Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
}
$eaLines += @(Show-NewLines "$dir\MQL5\Logs\*.log" 'ea') | Where-Object { $_ -match '\[AMS\]' }

# 記録を reports/live にまとめる（口座番号やパスワードは含めない）
foreach ($f in 'AMS_live_deals.csv', 'AMS_live_account.csv') {
  $src = Join-Path $common $f
  if (Test-Path $src) { Get-Content $src | Out-File (Join-Path $outDir $f) -Encoding utf8 }
}
$stamp = $start.ToString('yyyyMMdd_HHmm')
New-Item -ItemType Directory -Force -Path "$outDir\logs" | Out-Null
$eaLines | Out-File "$outDir\logs\$stamp.log" -Encoding utf8
Write-Host "EA のログ $($eaLines.Count) 行を保存しました"
