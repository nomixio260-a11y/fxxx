# GitHub Actions（Windows）用：EA とスクリプトをコンパイルし、エラー0・警告0 を確認する
$ErrorActionPreference = 'Stop'
$dir  = $env:MT5_DIR
$repo = $env:GITHUB_WORKSPACE

New-Item -ItemType Directory -Force -Path "$dir\MQL5\Include\AMS", "$dir\MQL5\Experts", "$dir\MQL5\Scripts", "$repo\reports" | Out-Null
Copy-Item "$repo\MQL5\Include\AMS\*.mqh" "$dir\MQL5\Include\AMS\" -Force
Copy-Item "$repo\MQL5\Experts\*.mq5" "$dir\MQL5\Experts\" -Force
Copy-Item "$repo\MQL5\Scripts\*.mq5" "$dir\MQL5\Scripts\" -Force

$targets = @('Experts\AdaptiveMultiStrategyEA', 'Scripts\AMS_ImportHistData')
$failed = $false
$all = @()
foreach ($t in $targets) {
  $name = Split-Path $t -Leaf
  $log  = Join-Path $dir "compile_$name.log"
  $ex5  = Join-Path $dir "MQL5\$t.ex5"
  Remove-Item $log, $ex5 -ErrorAction SilentlyContinue
  $meArgs = @("/compile:`"$dir\MQL5\$t.mq5`"", "/inc:`"$dir\MQL5`"", "/log:`"$log`"")
  Start-Process -FilePath (Join-Path $dir 'MetaEditor64.exe') -ArgumentList $meArgs -Wait | Out-Null
  if (-not (Test-Path $log)) { Write-Host "NG: $name のログがありません"; $failed = $true; continue }
  $text = Get-Content $log -Encoding Unicode | Where-Object { $_ -notmatch 'generating code' }
  $all += $text
  $result = ($text | Select-String -Pattern 'Result:' | Select-Object -Last 1).Line
  if ((Test-Path $ex5) -and ($result -match '0 errors?, 0 warnings?')) {
    Write-Host "OK: $name.ex5 ($result)"
  } else {
    Write-Host "NG: $name ($result)"
    $text | Select-String -Pattern 'error|warning' | ForEach-Object { Write-Host $_.Line }
    $failed = $true
  }
}
$all | Out-File -FilePath "$repo\reports\compile_windows.log" -Encoding utf8
if ($failed) { exit 1 }
