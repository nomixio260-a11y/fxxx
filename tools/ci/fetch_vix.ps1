# VIX の日次の終値（1990年〜）を公開データから取得して、MT5 の共通フォルダに AMS_vix.csv として置く。
#   方式 8（株価指数の層）の「VIX の状態による建玉の倍率」（98章）が読む。行の形は「日付(yyyy.MM.dd),終値」。
#   取得元：CBOE（公式）。だめなら FRED（VIXCLS）。どちらも取れなければ、ファイルは置かない（EA は倍率 1.0 のまま動く）。
#   EA は、判定する日足より前の日付の行だけを使うので、ファイルに新しい日付が入っていても、検証で未来の値を見ることはない。
$ErrorActionPreference = 'Continue'
$common = Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files'
New-Item -ItemType Directory -Force -Path $common | Out-Null
$dst = Join-Path $common 'AMS_vix.csv'
$rows = New-Object System.Collections.Generic.List[string]

function Get-Text($url) {
  for ($i = 0; $i -lt 3; $i++) {
    try {
      return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 90 -Headers @{ 'User-Agent' = 'Mozilla/5.0' }).Content
    } catch {
      Write-Host "VIX の取得に失敗（$($i + 1) 回目）: $($_.Exception.Message)"
      Start-Sleep -Seconds (5 * ($i + 1))
    }
  }
  return $null
}

$t = Get-Text 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
if ($t) {
  if ($t -is [byte[]]) { $t = [System.Text.Encoding]::ASCII.GetString($t) }
  foreach ($line in ($t -split "`n")) {
    if ($line -match '^\s*(\d{2})/(\d{2})/(\d{4}),[^,]*,[^,]*,[^,]*,\s*([0-9.]+)\s*$') { $rows.Add("$($matches[3]).$($matches[1]).$($matches[2]),$($matches[4])") }
  }
}
if ($rows.Count -lt 5000) {
  $rows.Clear()
  $t = Get-Text 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS'
  if ($t) {
    if ($t -is [byte[]]) { $t = [System.Text.Encoding]::ASCII.GetString($t) }
    foreach ($line in ($t -split "`n")) {
      if ($line -match '^\s*(\d{4})-(\d{2})-(\d{2}),\s*([0-9.]+)\s*$') { $rows.Add("$($matches[1]).$($matches[2]).$($matches[3]),$($matches[4])") }
    }
  }
}
if ($rows.Count -ge 5000) {
  $rows | Out-File -FilePath $dst -Encoding ascii
  Write-Host "VIX: $($rows.Count) 日分を $dst に置きました（最初 $($rows[0])、最後 $($rows[$rows.Count - 1])）"
} else {
  Write-Host "VIX を取得できませんでした（$($rows.Count) 行）。EA は VIX の倍率を 1.0 のままにします"
}
