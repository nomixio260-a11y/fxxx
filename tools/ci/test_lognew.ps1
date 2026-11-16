# lognew.ps1（Show-NewLines）の動作確認：UTF-16 のログに行を書き足しながら、新しい行だけが返るかを確かめる
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lognew.ps1')
$dir = Join-Path $env:RUNNER_TEMP 'lognew_test'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$f = Join-Path $dir 'a.log'
[System.IO.File]::WriteAllText($f, "line1`r`nline2 [AMS] x`r`n", [System.Text.Encoding]::Unicode)
$r1 = @(Show-NewLines "$dir\*.log" 't')
[System.IO.File]::AppendAllText($f, "line3`r`nhalf", [System.Text.Encoding]::Unicode)
$r2 = @(Show-NewLines "$dir\*.log" 't')
[System.IO.File]::AppendAllText($f, "-done`r`n", [System.Text.Encoding]::Unicode)
$r3 = @(Show-NewLines "$dir\*.log" 't')
$r4 = @(Show-NewLines "$dir\*.log" 't')
Write-Host "r1=$($r1 -join '|') r2=$($r2 -join '|') r3=$($r3 -join '|') r4count=$($r4.Count)"
if (($r1 -join '|') -ne 'line1|line2 [AMS] x' -or ($r2 -join '|') -ne 'line3' -or ($r3 -join '|') -ne 'half-done' -or $r4.Count -ne 0) { throw 'NG: Show-NewLines の結果が想定と違います' }
# 大きなログでも速いか（10万行を書いてから、1行足して読む）
$sb = New-Object System.Text.StringBuilder
for ($i = 0; $i -lt 100000; $i++) { [void]$sb.Append("x $i`r`n") }
[System.IO.File]::AppendAllText($f, $sb.ToString(), [System.Text.Encoding]::Unicode)
$t = Measure-Command { $null = @(Show-NewLines "$dir\*.log" 't') }
[System.IO.File]::AppendAllText($f, "last`r`n", [System.Text.Encoding]::Unicode)
$t2 = Measure-Command { $r5 = @(Show-NewLines "$dir\*.log" 't') }
Write-Host ("10万行の読み込み {0:N1} 秒、その後の1行 {1:N3} 秒" -f $t.TotalSeconds, $t2.TotalSeconds)
Write-Host 'OK: Show-NewLines は正しく動きました'
