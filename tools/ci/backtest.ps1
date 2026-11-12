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
$reportName = "AMS_$($symbol -replace '[^A-Za-z0-9]', '_')_H1"

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
Period=H1
Model=$model
Optimization=0
FromDate=$from
ToDate=$to
ForwardMode=0
Deposit=1000000
Currency=JPY
Leverage=1:25
ExecutionMode=0
Visual=0
Report=reports\$reportName
ReplaceReport=1
ShutdownTerminal=1
"@
$conf = Join-Path $dir 'ams_tester.ini'
$ini | Out-File -FilePath $conf -Encoding ascii

Write-Host "Backtest: $symbol H1 $from - $to (model=$model, server=$($env:MT5_SERVER))"
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
  $deadline = (Get-Date).AddMinutes($timeoutMin)
  # 実行中のログを30秒ごとに表示し、致命的なエラーが出たら早めに止める
  while (-not $p.WaitForExit(30000)) {
    $new  = @(Show-NewLines "$dir\logs\*.log" 'terminal')
    $new += @(Show-NewLines "$dir\Tester\Agent-*\logs\*.log" 'tester')
    $fatal = $new | Where-Object {
      ($_ -match 'authorization on .* failed') -or ($_ -match "tester didn't start") -or
      ($_ -match 'tester not started') -or ($_ -match 'symbol .* not (exist|found)')
    }
    $noConn += @($new | Where-Object { $_ -match 'no connection|server .* not found|common error|invalid server' }).Count
    if (-not $fatal -and $noConn -ge 5) { $fatal = @('接続エラーが繰り返し発生（サーバー名が見つからない可能性）') }
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
  Show-NewLines "$dir\Tester\Agent-*\logs\*.log" 'tester' | Out-Null
} finally {
  Remove-Item $conf -ErrorAction SilentlyContinue   # パスワードを含むので必ず削除
}

# レポート・ログの回収（ログは UTF-16 → UTF-8）
Get-ChildItem "$dir\reports\$reportName*" -ErrorAction SilentlyContinue | Copy-Item -Destination $out -Force
$common = Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\AMS_breakdown.csv'
if (Test-Path $common) { Get-Content $common | Out-File "$out\AMS_breakdown.csv" -Encoding utf8 }
$termLog = Get-ChildItem "$dir\logs\*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if ($termLog) { Get-Content $termLog.FullName -Encoding Unicode | Out-File "$out\terminal_last.log" -Encoding utf8 }
$agentLog = Get-ChildItem "$dir\Tester" -Recurse -Filter *.log -ErrorAction SilentlyContinue | Where-Object { $_.DirectoryName -like '*logs*' } | Sort-Object LastWriteTime | Select-Object -Last 1
if ($agentLog) { Get-Content $agentLog.FullName -Encoding Unicode | Out-File "$out\tester_last.log" -Encoding utf8 }

if (-not (Get-ChildItem "$out\$reportName*" -ErrorAction SilentlyContinue)) {
  Write-Host '--- terminal log (tail) ---'
  if (Test-Path "$out\terminal_last.log") { Get-Content "$out\terminal_last.log" -Tail 40 }
  Write-Host 'NG: レポートが作られませんでした（ログイン失敗・サーバー名違い・銘柄名違いの可能性）'
  exit 1
}
Write-Host 'OK: レポートを作成しました'
