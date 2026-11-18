# デモ口座の運用で、各回をいつ終えるかを決める（時刻はすべて UTC）。live.ps1 と test_schedule.ps1 から読み込む。
# 決まり：
# - 時刻ルールの取引の時間帯（前に20分・後に10分の余裕をつける）の途中で、回を入れ替えない。
#     東京 8:00〜12:00・17:00〜19:00・22:00〜24:00（日本時間。夏時間はない）
#     ロンドン 11:00〜13:00（イギリスの夏時間に合わせる）
#   続いている時間帯（例：日本時間 8:00〜12:00）は、1つの回で最初から最後まで受け持つ。
# - UTC 4:00 ごろに動いている回は、GitHub のサーバーごと止まる（2026年11月の実行6・7・14・19。
#   始めた時刻はばらばらだが、どれも UTC 4:08〜4:13 に失敗と記録された）。止まると、その回の状態と記録が保存されない。
#   そのため、東京の朝の回は UTC 3:35 までに終えて保存する。UTC 3:10〜4:20 に始まった回は、4:20 まで MT5 を起動せずに待つ
#   （待っているあいだに止められても、失うものはない。次の回は始めに予約してある）。
# - 1回の長さは、GitHub の上限（6時間）に余裕を残して、始まりから最大345分。

$script:LondonTz = $null
foreach ($id in 'GMT Standard Time', 'Europe/London') {
  try { $script:LondonTz = [TimeZoneInfo]::FindSystemTimeZoneById($id); break } catch { }
}

# 取引の時間帯の一覧（UTC、重なりはつなげる）。-Core を付けると、余裕なしの本来の時間帯
function Get-BusyIntervals([datetime]$fromUtc, [int]$days = 2, [switch]$Core) {
  $pre = 20; $post = 10
  if ($Core) { $pre = 0; $post = 0 }
  $list = New-Object System.Collections.Generic.List[object]
  for ($i = -1; $i -le $days; $i++) {
    $d = [datetime]::SpecifyKind($fromUtc.Date.AddDays($i), [DateTimeKind]::Utc)
    # 東京（日本時間の分。UTC は 540分 = 9時間引く）
    foreach ($w in @(@(480, 720), @(1020, 1140), @(1320, 1440))) {
      $list.Add(@($d.AddMinutes($w[0] - $pre - 540), $d.AddMinutes($w[1] + $post - 540)))
    }
    # ロンドン 11:00〜13:00
    $l0 = [datetime]::SpecifyKind($d, [DateTimeKind]::Unspecified)
    $ls = [TimeZoneInfo]::ConvertTimeToUtc($l0.AddMinutes(660 - $pre), $script:LondonTz)
    $le = [TimeZoneInfo]::ConvertTimeToUtc($l0.AddMinutes(780 + $post), $script:LondonTz)
    $list.Add(@($ls, $le))
  }
  $sorted = @($list | Sort-Object { $_[0] })
  $merged = New-Object System.Collections.Generic.List[object]
  foreach ($iv in $sorted) {
    $last = $merged.Count - 1
    if ($last -ge 0 -and $iv[0] -le $merged[$last][1]) {
      if ($iv[1] -gt $merged[$last][1]) { $merged[$last] = @($merged[$last][0], $iv[1]) }
    } else {
      $merged.Add($iv)
    }
  }
  return ,$merged
}

# 時刻 t を含む時間帯（なければ $null）
function Find-Busy([datetime]$t, $busy) {
  foreach ($iv in $busy) {
    if ($t -ge $iv[0] -and $t -lt $iv[1]) { return ,$iv }
  }
  return $null
}

# この回の予定：SleepUntil（MT5 を起動するまで待つ時刻、待たないなら $null）・Start（MT5 を動かし始める時刻）・End（終える時刻）・Note
function Get-LiveSchedule([datetime]$nowUtc, [int]$runMin = 330, [int]$maxJobMin = 345) {
  $day = [datetime]::SpecifyKind($nowUtc.Date, [DateTimeKind]::Utc)
  $sleepUntil = $null
  $tradeStart = $nowUtc
  if ($nowUtc -ge $day.AddMinutes(190) -and $nowUtc -lt $day.AddMinutes(260)) {   # UTC 3:10〜4:20
    $sleepUntil = $day.AddMinutes(260)
    $tradeStart = $sleepUntil
  }
  $hardEnd = $nowUtc.AddMinutes($maxJobMin)
  $cut = [datetime]::SpecifyKind($tradeStart.Date, [DateTimeKind]::Utc).AddMinutes(215)   # 次の UTC 3:35 までに終える
  if ($cut -le $tradeStart) { $cut = $cut.AddDays(1) }
  $maxEnd = if ($hardEnd -lt $cut) { $hardEnd } else { $cut }
  $target = $tradeStart.AddMinutes($runMin)
  if ($target -gt $maxEnd) { $target = $maxEnd }
  $b = Find-Busy $target (Get-BusyIntervals $tradeStart 2)
  $end = $target; $note = 'ok'
  if ($b) {
    if (($b[0] - $tradeStart).TotalMinutes -ge 30) { $end = $b[0]; $note = 'before' }   # 時間帯の前に終える
    elseif ($b[1] -le $maxEnd) { $end = $b[1]; $note = 'cover' }                         # 時間帯の終わりまで動かす
    else { $end = $maxEnd; $note = 'forced' }                                            # どうしても途中で入れ替わる
  }
  return [pscustomobject]@{ SleepUntil = $sleepUntil; Start = $tradeStart; End = $end; Note = $note }
}
