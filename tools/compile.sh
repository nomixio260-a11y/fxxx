#!/usr/bin/env bash
# MetaEditor のコマンドラインで EA とスクリプトをコンパイルし、エラー0・警告0 を確認する。
#   bash tools/compile.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

MT5=$(find_mt5_dir) || { echo "ERROR: MT5 が見つかりません。先に tools/install_mt5.sh を実行してください。" >&2; exit 1; }

# リポジトリのソースを MT5 の MQL5 フォルダへコピー
mkdir -p "$MT5/MQL5/Experts" "$MT5/MQL5/Scripts" "$MT5/MQL5/Include/AMS"
cp "$REPO_ROOT"/MQL5/Experts/*.mq5 "$MT5/MQL5/Experts/"
cp "$REPO_ROOT"/MQL5/Scripts/*.mq5 "$MT5/MQL5/Scripts/"
cp "$REPO_ROOT"/MQL5/Include/AMS/*.mqh "$MT5/MQL5/Include/AMS/"

TARGETS=("Experts/AdaptiveMultiStrategyEA" "Scripts/AMS_ImportHistData")
: > "$REPO_ROOT/reports/compile.log"
failed=0

for target in "${TARGETS[@]}"; do
  name=$(basename "$target")
  winrel="MQL5\\${target//\//\\}"
  LOG="$MT5/compile_$name.log"
  rm -f "$LOG" "$MT5/MQL5/$target.ex5"

  ( cd "$MT5" && xvfb-run -a wine MetaEditor64.exe \
      /compile:"$winrel.mq5" /inc:"MQL5" /log:"compile_$name.log" ) || true
  wineserver -w || true

  if [[ ! -f "$LOG" ]]; then
    echo "NG: $name のコンパイルログが作られませんでした。" >&2
    failed=1; continue
  fi
  utf16_to_utf8 "$LOG" | grep -v "generating code" >> "$REPO_ROOT/reports/compile.log"
  RESULT=$(utf16_to_utf8 "$LOG" | grep -Ei "result:? *[0-9]+ errors?, *[0-9]+ warnings?" | tail -1 || true)

  if [[ -f "$MT5/MQL5/$target.ex5" ]] && echo "$RESULT" | grep -Eqi "0 errors?, *0 warnings?"; then
    echo "OK: $name.ex5（$RESULT）"
  else
    echo "NG: $name — $RESULT" >&2
    utf16_to_utf8 "$LOG" | grep -Ei "error|warning" | grep -v "Result" >&2 || true
    failed=1
  fi
done
exit $failed
