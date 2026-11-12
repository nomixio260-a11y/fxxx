#!/usr/bin/env bash
# MetaEditor のコマンドラインで EA をコンパイルし、エラー0・警告0 を確認する。
#   bash tools/compile.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

MT5=$(find_mt5_dir) || { echo "ERROR: MT5 が見つかりません。先に tools/install_mt5.sh を実行してください。" >&2; exit 1; }
EA_NAME="AdaptiveMultiStrategyEA"

# リポジトリのソースを MT5 の MQL5 フォルダへコピー
mkdir -p "$MT5/MQL5/Experts" "$MT5/MQL5/Include/AMS"
cp "$REPO_ROOT/MQL5/Experts/$EA_NAME.mq5" "$MT5/MQL5/Experts/"
cp "$REPO_ROOT/MQL5/Include/AMS/"*.mqh "$MT5/MQL5/Include/AMS/"

LOG="$MT5/compile_$EA_NAME.log"
rm -f "$LOG" "$MT5/MQL5/Experts/$EA_NAME.ex5"

( cd "$MT5" && xvfb-run -a wine metaeditor64.exe \
    /compile:"MQL5\\Experts\\$EA_NAME.mq5" \
    /inc:"MQL5" \
    /log:"compile_$EA_NAME.log" ) || true
wineserver -w || true

if [[ ! -f "$LOG" ]]; then
  echo "ERROR: コンパイルログが作られませんでした。" >&2
  exit 1
fi

utf16_to_utf8 "$LOG" | tee "$REPO_ROOT/reports/compile.log"
RESULT=$(utf16_to_utf8 "$LOG" | grep -Ei "result:? *[0-9]+ errors?, *[0-9]+ warnings?" | tail -1 || true)
echo "----"
echo "$RESULT"

if [[ -f "$MT5/MQL5/Experts/$EA_NAME.ex5" ]] && echo "$RESULT" | grep -Eqi "0 errors?, *0 warnings?"; then
  echo "OK: $EA_NAME.ex5 を作成しました（エラー0・警告0）"
else
  echo "NG: エラーまたは警告があります。上のログを確認してください。" >&2
  exit 1
fi
