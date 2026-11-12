#!/usr/bin/env bash
# MT5（Wine）用の共通設定。他のスクリプトから source して使う。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export WINEPREFIX="${WINEPREFIX:-$HOME/.mt5}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEARCH="${WINEARCH:-win64}"

# MT5 のインストール先（OANDA 版は「OANDA MetaTrader 5」などのフォルダ名になる）
find_mt5_dir() {
  if [[ -n "${MT5_DIR:-}" && -f "$MT5_DIR/terminal64.exe" ]]; then
    echo "$MT5_DIR"; return 0
  fi
  local d
  for d in "$WINEPREFIX/drive_c/Program Files/"*/; do
    if [[ -f "${d}terminal64.exe" ]]; then
      echo "${d%/}"; return 0
    fi
  done
  return 1
}

# Wine の Windows パスに変換（Z: ドライブ経由）
winpath() {
  winepath -w "$1" 2>/dev/null
}

# UTF-16 のログ/レポートを UTF-8 に変換して出力
utf16_to_utf8() {
  local f="$1"
  if head -c 2 "$f" | od -An -tx1 | grep -qi "ff fe"; then
    iconv -f UTF-16LE -t UTF-8 "$f" | sed 's/^\xEF\xBB\xBF//; s/\r$//'
  else
    sed 's/\r$//' "$f"
  fi
}
