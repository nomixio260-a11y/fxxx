# MT5 のログ（UTF-16）から、前回読んだ位置より後に増えた行だけを読む。live.ps1 と test_lognew.ps1 から使う。
# ログは、前回読んだ位置から増えた分だけを読む（毎回ファイル全体を読み直すと、長く動かすほど重くなり、
# 2026年11月15〜16日にサーバーが途中で落ちる原因になったと考えられるため）
$script:pos  = @{}
$script:rest = @{}
function Show-NewLines([string]$pattern, [string]$tag) {
  $found = New-Object System.Collections.Generic.List[string]
  Get-ChildItem $pattern -ErrorAction SilentlyContinue | ForEach-Object {
    $path = $_.FullName
    $start = if ($script:pos.ContainsKey($path)) { $script:pos[$path] } else { 0 }
    if ($_.Length -lt $start) { $start = 0 }   # ファイルが作り直された
    if ($_.Length -eq $start) { return }
    try {
      $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
      try {
        [void]$fs.Seek($start, 'Begin')
        $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::Unicode)
        $text = $sr.ReadToEnd()
        $script:pos[$path] = $fs.Length
      } finally { $fs.Close() }
    } catch { return }
    if ($script:rest.ContainsKey($path)) { $text = $script:rest[$path] + $text }
    $parts = $text -split "`r?`n"
    # 最後の行が途中までなら、次の回に回す
    $script:rest[$path] = $parts[-1]
    for ($i = 0; $i -lt $parts.Count - 1; $i++) {
      $line = $parts[$i].TrimStart([char]0xFEFF)
      if ($line -eq '') { continue }
      # ログイン成功の確認は、口座番号を隠す前に行う
      if ($line -match 'authorized on') { $script:authorized = $true }
      # 口座番号を含む行は表示しない（ログは公開されるため）
      if ($env:MT5_LOGIN -and $line.Contains($env:MT5_LOGIN)) { continue }
      # 画面に出すのは、EA のメッセージと、ログイン・接続・エラーに関する行だけ（出力を増やしすぎないため）
      if ($line -match '\[AMS\]|authoriz|error|failed|disconnect|connection|stopped|initialized|loaded successfully') { Write-Host "[$tag] $line" }
      $found.Add($line)
    }
  }
  return $found
}

