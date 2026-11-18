# schedule.ps1 の自己テスト：1年分（夏時間の切り替えを含む）の回のつなぎを試算し、決まりが守られているか確かめる
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'schedule.ps1')
if (-not $script:LondonTz) { Write-Host 'NG: ロンドンのタイムゾーンが見つかりません'; exit 1 }

$fail = 0
foreach ($killed in @($true, $false)) {
  $t    = [datetime]::SpecifyKind([datetime]'2026-01-01T00:00:00', [DateTimeKind]::Utc)
  $stop = $t.AddDays(370)
  $n = 0; $bad = 0; $minH = 99.0; $maxH = 0.0
  $examples = New-Object System.Collections.Generic.List[string]
  while ($t -lt $stop) {
    $s = Get-LiveSchedule $t 330
    $n++
    if ($s.SleepUntil -and $killed -and $t.TimeOfDay.TotalMinutes -lt 240) {
      # UTC 4:00 ごろに止められ、次の回が 4:12 に始まる場合
      if (($t.Month -eq 1 -and $t.Day -eq 14) -or ($t.Month -eq 7 -and $t.Day -eq 15)) { $examples.Add("$($t.ToString('MM-dd HH:mm'))（待機中に停止）") }
      $t = [datetime]::SpecifyKind($t.Date, [DateTimeKind]::Utc).AddMinutes(252)
      continue
    }
    $msg = @()
    $len = ($s.End - $s.Start).TotalHours
    if ($len -lt $minH) { $minH = $len }
    if ($len -gt $maxH) { $maxH = $len }
    if (($s.End - $t).TotalMinutes -gt 345) { $msg += '長すぎる' }
    if (($s.End - $s.Start).TotalMinutes -lt 25) { $msg += '短すぎる' }
    if ($s.Note -eq 'forced') { $msg += '取引の時間帯の途中で入れ替え' }
    if (Find-Busy $s.End (Get-BusyIntervals $s.End 1 -Core)) { $msg += '取引の時間の途中で終わる' }
    $c = [datetime]::SpecifyKind($s.Start.Date, [DateTimeKind]::Utc).AddMinutes(225)   # UTC 3:45
    if ($c -lt $s.Start) { $c = $c.AddDays(1) }
    if ($c -lt $s.End) { $msg += 'UTC 3:45 に MT5 が動いている' }
    if ($msg.Count -gt 0) {
      $bad++
      if ($bad -le 5) { Write-Host "NG $($t.ToString('yyyy-MM-dd HH:mm')) → $($s.End.ToString('MM-dd HH:mm')) $($s.Note): $($msg -join '、')" }
    }
    if (($t.Month -eq 1 -and $t.Day -eq 14) -or ($t.Month -eq 7 -and $t.Day -eq 15)) {
      $examples.Add("$($t.ToString('MM-dd HH:mm'))→$($s.End.ToString('HH:mm'))($($s.Note))")
    }
    $t = $s.End.AddMinutes(3)
  }
  Write-Host ("UTC 4:00 に止まる={0}：{1} 回、決まりに合わない回 {2}、MT5 を動かす長さ {3:N1}〜{4:N1} 時間" -f $killed, $n, $bad, $minH, $maxH)
  if ($killed) { Write-Host ('  例（UTC）：' + ($examples -join ' | ')) }
  if ($bad -gt 0) { $fail = 1 }
}
if ($fail) { Write-Host 'NG: 回の区切りの決まりが守られていません'; exit 1 }
Write-Host 'OK: 回の区切りの決まりは守られています'
