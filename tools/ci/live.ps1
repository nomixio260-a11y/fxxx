# GitHub Actions（Windows）用：OANDA デモ口座で EA を実際に動かす（フォワードテスト）
# 必要なシークレット: MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
# 環境変数:
#   LIVE_MINUTES  この回で動かす最大の分数（既定 330）
#   LIVE_PRESET   使うプリセット（MQL5\Presets のファイル名、既定 AMS_Calendar_Portfolio.set）
#   LIVE_SYMBOL   EA を付けるチャートの銘柄（既定 USDJPY）
#   LIVE_OUT_DIR  成績の置き場所（既定 reports\live）
$ErrorActionPreference = 'Stop'
$dir    = $env:MT5_DIR
$repo   = $env:GITHUB_WORKSPACE
$runMin = if ($env:LIVE_MINUTES) { [int]$env:LIVE_MINUTES } else { 330 }
$preset = if ($env:LIVE_PRESET) { $env:LIVE_PRESET } else { 'AMS_Calendar_Portfolio.set' }
$symbol = if ($env:LIVE_SYMBOL) { $env:LIVE_SYMBOL } else { 'USDJPY' }
$common = Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
# 成績の置き場所（口座ごとに分ける。既定は為替の口座の reports\live、株価指数の口座は reports\live_index）
$outDir = Join-Path $repo $(if ($env:LIVE_OUT_DIR) { $env:LIVE_OUT_DIR } else { 'reports\live' })
New-Item -ItemType Directory -Force -Path "$dir\MQL5\Presets", $common, $outDir | Out-Null
Copy-Item "$repo\MQL5\Presets\*.set" "$dir\MQL5\Presets\" -Force
# 株価指数の層（方式 8）は、VIX の日次の終値を共通フォルダのファイルから読む（98章）。回のたびに取り直す。
#   取得できなくても止めない（EA は、ファイルがない・古いときは倍率 1.0 のまま動く）
if ((Get-Content (Join-Path $repo "MQL5\Presets\$preset") -ErrorAction SilentlyContinue) -match '^\s*InpEntryMode\s*=\s*8\s*$') {
  try { & (Join-Path $PSScriptRoot 'fetch_vix.ps1') } catch { Write-Host "注意：VIX の取得に失敗しました（$($_.Exception.Message)）" }
}

# 終わる時刻を決める（UTC、tools/ci/schedule.ps1）。
#   取引の時間帯の途中で回を入れ替えない。UTC 4:00 ごろにサーバーごと止まる問題を避けるため、東京の朝の回は 3:35 までに終えて保存し、
#   UTC 3:10〜4:20 に始まった回は 4:20 まで MT5 を起動せずに待つ。計算に失敗したときは、決めた分数だけ動かす。
try {
  . (Join-Path $PSScriptRoot 'schedule.ps1')
  $sch = Get-LiveSchedule (Get-Date).ToUniversalTime() $runMin
} catch {
  Write-Host "注意：終わる時刻の計算に失敗したため、$runMin 分で終えます（$($_.Exception.Message)）"
  $now = (Get-Date).ToUniversalTime()
  $sch = [pscustomobject]@{ SleepUntil = $null; Start = $now; End = $now.AddMinutes($runMin); Note = 'fallback' }
}
# 30分以下の短い回（建玉の決済だけを行う回など）は、待たずにすぐ動かし、決めた分数で終える
if ($runMin -le 30) {
  $now = (Get-Date).ToUniversalTime()
  $sch = [pscustomobject]@{ SleepUntil = $null; Start = $now; End = $now.AddMinutes($runMin); Note = 'short' }
}
if ($sch.SleepUntil) {
  Write-Host "UTC 4:00 ごろはサーバーが止まることがあるため、$($sch.SleepUntil.ToString('HH:mm')) UTC まで MT5 を起動せずに待ちます"
  $wait = ($sch.SleepUntil - (Get-Date).ToUniversalTime()).TotalSeconds
  if ($wait -gt 0) { Start-Sleep -Seconds ([int][math]::Ceiling($wait)) }
}
$start = (Get-Date).ToUniversalTime()
$end   = $sch.End
Write-Host "開始 $($start.ToString('yyyy-MM-dd HH:mm')) UTC → 終了予定 $($end.ToString('yyyy-MM-dd HH:mm')) UTC（$($sch.Note)、プリセット $preset）"
"LIVE_END_UTC=$($end.ToString('o'))" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

# 注文を許すか（既定は 1。観察だけの回は LIVE_ALLOW_TRADING=0 にして、端末の側でも注文を禁止する）
$allowTrading = if ($env:LIVE_ALLOW_TRADING -eq '0') { '0' } else { '1' }
if ($allowTrading -eq '0') { Write-Host '観察だけの回です：端末の設定で自動売買を禁止しています（注文は出ません）' }
$ini = @"
[Common]
Login=$($env:MT5_LOGIN)
Password=$($env:MT5_PASSWORD)
Server=$($env:MT5_SERVER)
KeepPrivate=1
NewsEnable=0

[Experts]
AllowLiveTrading=$allowTrading
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

# ログの新しい行だけを読む関数（tools/ci/lognew.ps1）
. (Join-Path $PSScriptRoot 'lognew.ps1')

$eaLines = New-Object System.Collections.Generic.List[string]
try {
  $p = Start-Process -FilePath (Join-Path $dir 'terminal64.exe') -ArgumentList '/portable', "/config:`"$conf`"" -PassThru
  Start-Sleep -Seconds 90
  Remove-Item $conf -ErrorAction SilentlyContinue   # パスワードを含むので、起動したらすぐ消す
  $script:authorized = $false
  while ((Get-Date).ToUniversalTime() -lt $end) {
    if ($p.HasExited) { Write-Host 'ターミナルが終了しました'; break }
    $new = @(Show-NewLines "$dir\logs\*.log" 'terminal')
    $ea  = @(Show-NewLines "$dir\MQL5\Logs\*.log" 'ea')
    foreach ($l in $ea) { if ($l -match '\[AMS\]') { $eaLines.Add($l) } }
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
foreach ($l in @(Show-NewLines "$dir\MQL5\Logs\*.log" 'ea')) { if ($l -match '\[AMS\]') { $eaLines.Add($l) } }

# 記録を reports/live にまとめる（口座番号やパスワードは含めない）
foreach ($f in 'AMS_live_deals.csv', 'AMS_live_account.csv') {
  $src = Join-Path $common $f
  if (Test-Path $src) { Get-Content $src | Out-File (Join-Path $outDir $f) -Encoding utf8 }
}
# 研究用の書き出し（観察モードの InpIxExportSymbols）。リポジトリには入れず、ワークフローの成果物として残す
$exp = @(Get-ChildItem $common -Filter 'AMS_d1_*.csv' -ErrorAction SilentlyContinue) + @(Get-ChildItem $common -Filter 'AMS_ix_symbols.csv' -ErrorAction SilentlyContinue)
if ($exp.Count -gt 0) {
  New-Item -ItemType Directory -Force -Path "$outDir\export" | Out-Null
  $exp | Copy-Item -Destination "$outDir\export" -Force
  Write-Host "書き出したファイル $($exp.Count) 個を $outDir\export に集めました"
}
$stamp = $start.ToString('yyyyMMdd_HHmm')
New-Item -ItemType Directory -Force -Path "$outDir\logs" | Out-Null
$eaLines | Out-File "$outDir\logs\$stamp.log" -Encoding utf8
Write-Host "EA のログ $($eaLines.Count) 行を保存しました"
