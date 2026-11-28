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
# テスターの口座のレバレッジ（為替の口座は 25 倍。株価指数の CFD は 10 倍なので、指数の検証では 10 を指定する）
$leverage = if ($env:BT_LEVERAGE) { $env:BT_LEVERAGE } else { '25' }
$tfValue = @{ 'M1' = 1; 'M5' = 5; 'M15' = 15; 'M30' = 30; 'H1' = 16385; 'H2' = 16386; 'H4' = 16388; 'D1' = 16408 }[$period]
if (-not $tfValue) { throw "未対応の時間足: $period" }
$reportName = "AMS_$($symbol -replace '[^A-Za-z0-9]', '_')_$period"

# EA の入力値の上書き（[TesterInputs]）。書式: 名前=値||開始||刻み||終了||Y/N
# 順番：BT_PRESET（実運用と同じプリセットファイル）→ BT_SYMBOLS → BT_INPUTS（あとのものが優先）
$kv = [ordered]@{}
if ($env:BT_PRESET) {
  $pf = Join-Path $repo "MQL5\Presets\$($env:BT_PRESET)"
  if (-not (Test-Path $pf)) { throw "プリセットが見つかりません: $($env:BT_PRESET)" }
  foreach ($line in (Get-Content $pf)) {
    if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$' -and -not $line.TrimStart().StartsWith(';')) { $kv[$matches[1]] = $matches[2] }
  }
  Write-Host "プリセット $($env:BT_PRESET) を読み込みました（$($kv.Count) 項目）"
}
if ($env:BT_SYMBOLS) { $kv['InpSymbols'] = $env:BT_SYMBOLS }
# BT_INPUTS: 「名前=値;名前=値」で任意の入力を固定値にする
if ($env:BT_INPUTS) {
  foreach ($item in ($env:BT_INPUTS -split ';')) {
    if ($item -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$') { $kv[$matches[1]] = $matches[2] }   # 値が空（名前=）なら、空の文字列にする
  }
}
$kv.Remove('InpTimeframe')   # 時間足は Period の指定に合わせる
$inputLines = @("InpTimeframe=$tfValue||$tfValue||0||$tfValue||N")
foreach ($k in $kv.Keys) {
  $v = $kv[$k]
  if ($v -eq '') { $inputLines += "$k="; continue }
  # 数値・true/false は「値||開始||刻み||終了||N」、文字列は「名前=値」だけを書く（|| が値の一部として扱われるため）
  if ($v -match '^-?[0-9.]+$' -or $v -match '^(true|false)$') { $inputLines += "$k=$v||$v||0||$v||N" }
  else { $inputLines += "$k=$v" }
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

# 仮の銘柄（公開の1分足から作るカスタム銘柄）。BT_CUSTOM に、カンマ区切りで名前を入れる（例: US500_HD,US100_HD,XAU_HD）。
#   口座に株価指数・金の CFD の銘柄がなくても、方式 8 を検証できるようにするためのもの。
#   data\custom\<名前>.csv（ワークフローの data ジョブが histdata.com から用意する）を、スクリプト AMS_ImportHistData で取り込む。
#   条件は実際の OANDA の CFD とは違う（目安として厳しめ）：スプレッドは固定、持ち越しのコストは一定の年率。
#   損益は円で計算する（1 ポイント = 100 円 × lot）。建玉は口座に対する割合で決めるので、成績（%）は通貨の換算に関係しない。
if ($env:BT_CUSTOM) {
  $spec = @{
    'US500_HD' = @{ Digits = 2; Spread = 100; SwapL = -3.0; SwapS = -1.0; Desc = 'S&P500 CFD (histdata.com M1)' }      # スプレッド 1.0 ポイント
    'US100_HD' = @{ Digits = 2; Spread = 250; SwapL = -3.8; SwapS = -1.0; Desc = 'NASDAQ100 CFD (histdata.com M1)' }   # スプレッド 2.5 ポイント
    'XAU_HD'   = @{ Digits = 2; Spread = 50;  SwapL = -4.4; SwapS = -0.5; Desc = 'Gold CFD (histdata.com M1)' }        # スプレッド 0.5 ドル
  }
  $chartSym = if ($env:BT_CHART_SYMBOL) { $env:BT_CHART_SYMBOL } else { 'USDJPY' }
  New-Item -ItemType Directory -Force -Path "$dir\MQL5\Files", "$dir\MQL5\Presets" | Out-Null
  foreach ($name in ($env:BT_CUSTOM -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    if (-not $spec.ContainsKey($name)) { throw "未対応の仮の銘柄: $name" }
    $csv = Join-Path $repo "data\custom\$name.csv"
    if (-not (Test-Path $csv)) { throw "仮の銘柄のデータがありません: $csv" }
    Copy-Item $csv "$dir\MQL5\Files\$name.csv" -Force
    $s = $spec[$name]
    @("InpFile=$name.csv", "InpSymbol=$name", "InpOrigin=", "InpSpreadPts=$($s.Spread)", "InpDigits=$($s.Digits)", "InpContract=100",
      "InpBase=JPY", "InpProfit=JPY", "InpMargin=JPY", "InpCfd=true", "InpMarginRate=0.1", "InpSwapLongPct=$($s.SwapL)",
      "InpSwapShortPct=$($s.SwapS)", "InpDescription=$($s.Desc)") | Out-File "$dir\MQL5\Presets\ams_import.set" -Encoding ascii
    $iconf = Join-Path $dir 'ams_import.ini'
    @"
[Common]
Login=$($env:MT5_LOGIN)
Password=$($env:MT5_PASSWORD)
Server=$($env:MT5_SERVER)
KeepPrivate=1
NewsEnable=0

[StartUp]
Script=AMS_ImportHistData
ScriptParameters=ams_import.set
Symbol=$chartSym
Period=H1
ShutdownTerminal=1
"@ | Out-File -FilePath $iconf -Encoding ascii
    Write-Host "仮の銘柄 $name を取り込みます（$([math]::Round((Get-Item $csv).Length / 1MB)) MB）"
    try {
      $ip = Start-Process -FilePath (Join-Path $dir 'terminal64.exe') -ArgumentList '/portable', "/config:`"$iconf`"" -PassThru
      if (-not $ip.WaitForExit(25 * 60 * 1000)) {
        Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
        throw "仮の銘柄 $name の取り込みが25分で終わりませんでした"
      }
    } finally {
      Remove-Item $iconf -ErrorAction SilentlyContinue   # パスワードを含むので必ず削除
    }
    $done = Get-ChildItem "$dir\MQL5\Logs\*.log" -ErrorAction SilentlyContinue | ForEach-Object { Get-Content $_.FullName -Encoding Unicode -ErrorAction SilentlyContinue } |
      Where-Object { $_ -match '\[AMS-Import\]' -and $_ -match [regex]::Escape($name) } | Select-Object -Last 1
    Write-Host "取り込みの結果: $done"
    if (-not ($done -match '完了')) {
      Get-ChildItem "$dir\logs\*.log" -ErrorAction SilentlyContinue | ForEach-Object { Get-Content $_.FullName -Encoding Unicode -Tail 30 -ErrorAction SilentlyContinue | Where-Object { -not $env:MT5_LOGIN -or $_ -notmatch [regex]::Escape($env:MT5_LOGIN) } | ForEach-Object { Write-Host "[terminal] $_" } }
      throw "仮の銘柄 $name の取り込みを確認できませんでした"
    }
    Remove-Item "$dir\MQL5\Files\$name.csv" -ErrorAction SilentlyContinue
  }
}
# 方式 8（株価指数の層）は、VIX の日次の終値を共通フォルダのファイルから読む（98章）。検証の前に置いておく
if ($kv['InpEntryMode'] -eq '8') { & (Join-Path $repo 'tools\ci\fetch_vix.ps1') }
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
Leverage=1:$leverage
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
  # 大きなログでも遅くならないように、新しい行はリストに集める（配列への += は行数の2乗の時間がかかる）
  $found = New-Object System.Collections.Generic.List[string]
  Get-ChildItem $pattern -ErrorAction SilentlyContinue | ForEach-Object {
    $lines = @(Get-Content $_.FullName -Encoding Unicode -ErrorAction SilentlyContinue)
    $start = if ($script:shown.ContainsKey($_.FullName)) { $script:shown[$_.FullName] } else { 0 }
    for ($i = $start; $i -lt $lines.Count; $i++) { Write-Host "[$tag] $($lines[$i])"; $found.Add($lines[$i]) }
    $script:shown[$_.FullName] = $lines.Count
  }
  return ,$found.ToArray()
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
    # テスターのログは、取引のたびに行が増えて膨大になるため、テスト中は表示しない（終わった後に最後の部分だけ表示する）
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
  if ($mode -ne 'optimize') {
    Get-ChildItem "$dir\Tester\Agent-*\logs\*.log" -ErrorAction SilentlyContinue | ForEach-Object {
      Get-Content $_.FullName -Encoding Unicode -Tail 300 -ErrorAction SilentlyContinue | Where-Object { -not $env:MT5_LOGIN -or $_ -notmatch [regex]::Escape($env:MT5_LOGIN) } | ForEach-Object { Write-Host "[tester] $_" }
    }
  }
} finally {
  Remove-Item $conf -ErrorAction SilentlyContinue   # パスワードを含むので必ず削除
}

# レポート・ログの回収（ログは UTF-16 → UTF-8）
Get-ChildItem "$dir\reports\$reportName*" -ErrorAction SilentlyContinue | Copy-Item -Destination $out -Force
foreach ($f in 'AMS_breakdown.csv', 'AMS_monthly.csv', 'AMS_rulemonth.csv', 'AMS_bt_deals.csv', 'AMS_symbols.csv') {
  $common = Join-Path $env:APPDATA "MetaQuotes\Terminal\Common\Files\$f"
  if (Test-Path $common) { Get-Content $common | Out-File "$out\$f" -Encoding utf8 }
}
# 調査用の足の書き出し（InpExportBars）
Get-ChildItem (Join-Path $env:APPDATA "MetaQuotes\Terminal\Common\Files") -Filter 'AMS_bars_*.csv' -ErrorAction SilentlyContinue | Copy-Item -Destination $out -Force
$termLog = Get-ChildItem "$dir\logs\*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
# ログは成果物として公開されるので、口座番号を含む行は書き出さない（ログインの行・接続の行に口座番号が入る）
function Remove-LoginLines($lines) {
  if (-not $env:MT5_LOGIN) { return $lines }
  $pat = [regex]::Escape($env:MT5_LOGIN)
  return @($lines | Where-Object { $_ -notmatch $pat })
}
if ($termLog) { Remove-LoginLines (Get-Content $termLog.FullName -Encoding Unicode) | Out-File "$out\terminal_last.log" -Encoding utf8 }
$agentLog = Get-ChildItem "$dir\Tester" -Recurse -Filter *.log -ErrorAction SilentlyContinue | Where-Object { $_.DirectoryName -like '*logs*' } | Sort-Object LastWriteTime | Select-Object -Last 1
if ($agentLog) { Remove-LoginLines (Get-Content $agentLog.FullName -Encoding Unicode) | Out-File "$out\tester_last.log" -Encoding utf8 }

# 動作確認用：取引の件数と、最初のほうの取引の抜粋（結果の1行要約と一緒に保存する）
if (Test-Path "$out\tester_last.log") {
  $tl = @(Get-Content "$out\tester_last.log" -Encoding utf8)
  $slN = @($tl | Where-Object { $_ -match 'stop loss triggered' }).Count
  $tpN = @($tl | Where-Object { $_ -match 'take profit triggered' }).Count
  $eaN = @($tl | Where-Object { $_ -match '\[AMS\] 決済 #' }).Count
  $soN = @($tl | Where-Object { $_ -match 'stop out' }).Count
  $ev  = @($tl | Where-Object { $_ -match '\[AMS\] \S+ (BUY|SELL) |stop loss triggered|take profit triggered|\[AMS\] 決済 #|週明け|エントリーの方式|DD上限|下落したため|自動調整|指数の層：\S+（|スワップの倍率|指数の層：値動きの見積もり|指数の層：その夜のスワップ|指数の層：ルールがそろった数の重み|指数の層：建玉の丸め方|状態の復元（|stop out|margin call' })
  $lines = @("SAMPLE sl_hit=$slN tp_hit=$tpN closed_by_ea=$eaN stop_out=$soN")
  $lines += ($ev | Select-Object -First 48 | ForEach-Object {
    $x = $_ -replace '^.*?\t(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+', '$1 '
    if ($x.Length -gt 150) { $x.Substring(0, 150) } else { $x }
  })
  # 終わりのまとめの行（区切りの前に手じまった回数など）
  $lines += @($tl | Where-Object { $_ -match '区切りの前に手じまった回数|強制ロスカットを避ける上限で建玉を縮めた回数|切り捨てより建玉が増えた回数|起動し直しを再現した回数|注文の失敗でやり直した回数' } | Select-Object -Last 5 | ForEach-Object { $_ -replace '^.*?\t(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+', '$1 ' })
  # 見送りの理由（最初の40件）
  $skip = @($tl | Where-Object { $_ -match '\[AMS\] 見送り' })
  $lines += "SKIPS total=$($skip.Count)"
  # 見送りの理由を、ルールごとに数える（全件。理由の細かい数字は除く）
  $lines += "SKIP_REASONS"
  $lines += @($skip | ForEach-Object {
      if ($_ -match '\[AMS\] 見送り \S+ \[([^\]]*)\] 理由=([^（(]*)') { "$($matches[1]) $($matches[2].Trim())" }
    } | Group-Object | Sort-Object Count -Descending | ForEach-Object { "  $($_.Count) $($_.Name)" })
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
