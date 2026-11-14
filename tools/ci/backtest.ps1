# GitHub Actions（Windows）用：OANDA デモ口座にログインしてストラテジーテスターを実行する
# 必要なシークレット: MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
$ErrorActionPreference = 'Stop'
$dir  = $env:MT5_DIR
$repo = $env:GITHUB_WORKSPACE
$out  = Join-Path $repo 'reports'
New-Item -ItemType Directory -Force -Path $out, "$dir\reports" | Out-Null

$symbol = if ($env:BT_SYMBOL) { $env:BT_SYMBOL } else { 'USDJPY' }
$from   = if ($env:BT_FROM)   { $env:BT_FROM }   else { (Get-Date).AddYears(-2).ToString('yyyy.MM.dd') }
$to     = if ($env:BT_TO)     { $env:BT_TO }     else { (Get-Date).ToString('yyyy.MM.dd') }
$model  = if ($env:BT_MODEL)  { $env:BT_MODEL }  else { '1' }
$mode   = if ($env:BT_MODE)   { $env:BT_MODE }   else { 'backtest' }
$period = if ($env:BT_PERIOD) { $env:BT_PERIOD } else { 'H1' }
# 約定の遅れ：-1=ランダムな遅延（実運用に近い）、0=遅延なし、正の数=ミリ秒。
# 既定は、通常のバックテストがランダム遅延、最適化は遅延なし（速度と再現性のため）
$execMode = if ($env:BT_EXECUTION) { $env:BT_EXECUTION } elseif ($mode -eq 'optimize') { '0' } else { '-1' }
$deposit  = if ($env:BT_DEPOSIT) { $env:BT_DEPOSIT } else { '1000000' }
$tfValue = @{ 'M5' = 5; 'M15' = 15; 'M30' = 30; 'H1' = 16385; 'H2' = 16386; 'H4' = 16388; 'D1' = 16408 }[$period]
if (-not $tfValue) { throw "未対応の時間足: $period" }
$reportName = "AMS_$($symbol -replace '[^A-Za-z0-9]', '_')_$period"

# EA の入力値の上書き（[TesterInputs]）。書式: 名前=値||開始||刻み||終了||Y/N
$inputLines = @("InpTimeframe=$tfValue||$tfValue||0||$tfValue||N")
if ($env:BT_SYMBOLS) { $inputLines += "InpSymbols=$($env:BT_SYMBOLS)" }
# BT_INPUTS: 「名前=値;名前=値」で任意の入力を固定値にする
if ($env:BT_INPUTS) {
  foreach ($kv in ($env:BT_INPUTS -split ';')) {
    if ($kv -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$') {
      $k = $matches[1]; $v = $matches[2]
      # 数値・true/false は「値||開始||刻み||終了||N」、文字列は「名前=値」だけを書く（|| が値の一部として扱われるため）
      if ($v -match '^-?[0-9.]+$' -or $v -match '^(true|false)$') { $inputLines += "$k=$v||$v||0||$v||N" }
      else { $inputLines += "$k=$v" }
    }
  }
}

# 最適化モード：前半で最適化（遺伝的アルゴリズム・カスタム評価値）、後半をフォワード検証に使う
$optLines = "Optimization=0`r`nForwardMode=0"
if ($mode -eq 'optimize') {
  $fwd = if ($env:BT_FORWARD) { $env:BT_FORWARD } else { (Get-Date).AddMonths(-10).ToString('yyyy.MM.01') }
  $optLines = "Optimization=2`r`nOptimizationCriterion=6`r`nForwardMode=4`r`nForwardDate=$fwd"
  $reportName = "AMS_opt_$($symbol -replace '[^A-Za-z0-9]', '_')_$period"
  $fixed = $inputLines | ForEach-Object { ($_ -split '=')[0] }
  $inputLines += (Get-Content (Join-Path $repo 'tester\optimize_inputs.ini') |
    Where-Object { $_ -and -not $_.StartsWith(';') -and ($fixed -notcontains ($_ -split '=')[0]) })
  Write-Host "最適化モード: フォワード開始日 $fwd"
}
$testerInputs = "`r`n[TesterInputs]`r`n" + ($inputLines -join "`r`n")
Write-Host "入力の上書き:`n$($inputLines -join "`n")"

$ini = @"
[Common]
Login=$($env:MT5_LOGIN)
Password=$($env:MT5_PASSWORD)
Server=$($env:MT5_SERVER)
KeepPrivate=1
NewsEnable=0

[Tester]
Expert=AdaptiveMultiStrategyEA.ex5
Symbol=$symbol
Period=$period
Model=$model
$optLines
FromDate=$from
ToDate=$to
Deposit=$deposit
Currency=JPY
Leverage=1:25
ExecutionMode=$execMode
Visual=0
Report=reports\$reportName
ReplaceReport=1
ShutdownTerminal=1
$testerInputs
"@
$conf = Join-Path $dir 'ams_tester.ini'
$ini | Out-File -FilePath $conf -Encoding ascii

Write-Host "Backtest: $symbol H1 $from - $to (mode=$mode, model=$model, execution=$execMode, deposit=$deposit, server=$($env:MT5_SERVER))"
# ログファイルの新しい行だけを表示する（MT5 のログは UTF-16）
$script:shown = @{}
function Show-NewLines([string]$pattern, [string]$tag) {
  $found = @()
  Get-ChildItem $pattern -ErrorAction SilentlyContinue | ForEach-Object {
    $lines = @(Get-Content $_.FullName -Encoding Unicode -ErrorAction SilentlyContinue)
    $start = if ($script:shown.ContainsKey($_.FullName)) { $script:shown[$_.FullName] } else { 0 }
    for ($i = $start; $i -lt $lines.Count; $i++) { Write-Host "[$tag] $($lines[$i])"; $found += $lines[$i] }
    $script:shown[$_.FullName] = $lines.Count
  }
  return $found
}

# 画面のスクリーンショット（ダイアログで止まっていないかの確認用）
function Save-Screen([string]$path) {
  try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Host "画面を保存: $path"
  } catch { Write-Host "画面の保存に失敗: $($_.Exception.Message)" }
}

try {
  $p = Start-Process -FilePath (Join-Path $dir 'terminal64.exe') -ArgumentList '/portable', "/config:`"$conf`"" -PassThru
  $timeoutMin = if ($env:BT_TIMEOUT_MIN) { [int]$env:BT_TIMEOUT_MIN } else { 25 }
  $noConn = 0
  $authorized = $false
  $startedAt = Get-Date
  $deadline = (Get-Date).AddMinutes($timeoutMin)
  # 実行中のログを30秒ごとに表示し、致命的なエラーが出たら早めに止める
  while (-not $p.WaitForExit(30000)) {
    $new  = @(Show-NewLines "$dir\logs\*.log" 'terminal')
    # 最適化中はエージェントのログが膨大になるので表示しない
    if ($mode -ne 'optimize') { $new += @(Show-NewLines "$dir\Tester\Agent-*\logs\*.log" 'tester') }
    $fatal = $new | Where-Object {
      ($_ -match 'authorization on .* failed') -or ($_ -match "tester didn't start") -or
      ($_ -match 'tester not started') -or ($_ -match 'symbol .* not (exist|found)')
    }
    $noConn += @($new | Where-Object { $_ -match 'no connection|server .* not found|common error|invalid server' }).Count
    if (-not $fatal -and $noConn -ge 5) { $fatal = @('接続エラーが繰り返し発生（サーバー名が見つからない可能性）') }
    if ($new | Where-Object { $_ -match 'authorized on' }) { $authorized = $true }
    if (-not $fatal -and -not $authorized -and ((Get-Date) - $startedAt).TotalMinutes -ge 6) {
      $fatal = @('6分たっても口座にログインできていません（サーバー名が MT5 のサーバー一覧に無い可能性）')
    }
    if ($fatal) {
      Save-Screen (Join-Path $out 'screen_at_error.png')
      Write-Host "エラーを検出したため停止します: $($fatal | Select-Object -First 1)"
      Get-Process terminal64, metatester64 -ErrorAction SilentlyContinue | Stop-Process -Force
      break
    }
    if ((Get-Date) -gt $deadline) {
      Write-Host "タイムアウト（$timeoutMin 分）。画面を保存してからターミナルを停止します。"
      Save-Screen (Join-Path $out 'screen_at_timeout.png')
      Get-Process terminal64, metatester64 -ErrorAction SilentlyContinue | Stop-Process -Force
      break
    }
  }
  Show-NewLines "$dir\logs\*.log" 'terminal' | Out-Null
  if ($mode -ne 'optimize') { Show-NewLines "$dir\Tester\Agent-*\logs\*.log" 'tester' | Out-Null }
} finally {
  Remove-Item $conf -ErrorAction SilentlyContinue   # パスワードを含むので必ず削除
}

# レポート・ログの回収（ログは UTF-16 → UTF-8）
Get-ChildItem "$dir\reports\$reportName*" -ErrorAction SilentlyContinue | Copy-Item -Destination $out -Force
foreach ($f in 'AMS_breakdown.csv', 'AMS_monthly.csv', 'AMS_rulemonth.csv', 'AMS_bt_deals.csv') {
  $common = Join-Path $env:APPDATA "MetaQuotes\Terminal\Common\Files\$f"
  if (Test-Path $common) { Get-Content $common | Out-File "$out\$f" -Encoding utf8 }
}
$termLog = Get-ChildItem "$dir\logs\*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if ($termLog) { Get-Content $termLog.FullName -Encoding Unicode | Out-File "$out\terminal_last.log" -Encoding utf8 }
$agentLog = Get-ChildItem "$dir\Tester" -Recurse -Filter *.log -ErrorAction SilentlyContinue | Where-Object { $_.DirectoryName -like '*logs*' } | Sort-Object LastWriteTime | Select-Object -Last 1
if ($agentLog) { Get-Content $agentLog.FullName -Encoding Unicode | Out-File "$out\tester_last.log" -Encoding utf8 }

# 動作確認用：取引の件数と、最初のほうの取引の抜粋（結果の1行要約と一緒に保存する）
if (Test-Path "$out\tester_last.log") {
  $tl = @(Get-Content "$out\tester_last.log" -Encoding utf8)
  $slN = @($tl | Where-Object { $_ -match 'stop loss triggered' }).Count
  $tpN = @($tl | Where-Object { $_ -match 'take profit triggered' }).Count
  $eaN = @($tl | Where-Object { $_ -match '\[AMS\] 決済 #' }).Count
  $soN = @($tl | Where-Object { $_ -match 'stop out' }).Count
  $ev  = @($tl | Where-Object { $_ -match '\[AMS\] \S+ (BUY|SELL) |stop loss triggered|take profit triggered|\[AMS\] 決済 #|週明け|エントリーの方式|DD上限|下落したため|自動調整' })
  $lines = @("SAMPLE sl_hit=$slN tp_hit=$tpN closed_by_ea=$eaN stop_out=$soN")
  $lines += ($ev | Select-Object -First 48 | ForEach-Object {
    $x = $_ -replace '^.*?\t(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+', '$1 '
    if ($x.Length -gt 150) { $x.Substring(0, 150) } else { $x }
  })
  # 見送りの理由（最初の40件）
  $skip = @($tl | Where-Object { $_ -match '\[AMS\] 見送り' })
  $lines += "SKIPS total=$($skip.Count)"
  $lines += ($skip | Select-Object -First 40 | ForEach-Object {
    $x = $_ -replace '^.*?\t(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+', '$1 '
    if ($x.Length -gt 150) { $x.Substring(0, 150) } else { $x }
  })
  $lines | Out-File "$out\trade_sample.txt" -Encoding utf8
}

if (-not (Get-ChildItem "$out\$reportName*" -ErrorAction SilentlyContinue)) {
  Write-Host '--- terminal log (tail) ---'
  if (Test-Path "$out\terminal_last.log") { Get-Content "$out\terminal_last.log" -Tail 40 }
  Write-Host 'NG: レポートが作られませんでした（ログイン失敗・サーバー名違い・銘柄名違いの可能性）'
  exit 1
}
Write-Host 'OK: レポートを作成しました'
