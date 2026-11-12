#!/usr/bin/env bash
# ブローカーにログインせずにバックテストする（histdata.com の実データをカスタム銘柄として使う）。
#   bash tools/fetch_histdata.sh USDJPY 2024 2026     # データ取得（data/USDJPY_M1.csv）
#   bash tools/backtest_custom.sh [開始日] [終了日]     # 例: 2024.03.01 2026.10.30
# 注意: スプレッドは固定（既定 0.4pips）、スワップなし。実際の OANDA 口座の条件とは異なる。
set -euo pipefail
source "$(dirname "$0")/common.sh"

MT5=$(find_mt5_dir) || { echo "ERROR: MT5 が見つかりません。" >&2; exit 1; }
CSV="${CSV:-$REPO_ROOT/data/USDJPY_M1.csv}"
SYMBOL="${SYMBOL:-USDJPY_HD}"
SPREAD_PTS="${SPREAD_PTS:-4}"
FROM_DATE="${1:-2024.03.01}"
TO_DATE="${2:-2026.10.30}"
[[ -f "$CSV" ]] || { echo "ERROR: $CSV がありません。先に tools/fetch_histdata.sh を実行してください。" >&2; exit 1; }

bash "$REPO_ROOT/tools/compile.sh"

# 1) CSV をカスタム銘柄に取り込む（起動時にスクリプトを実行し、終わったらターミナルを閉じる）
mkdir -p "$MT5/MQL5/Files"
cp "$CSV" "$MT5/MQL5/Files/$(basename "$CSV")"
cat > "$MT5/ams_import.ini" <<EOF
[StartUp]
Script=AMS_ImportHistData
ScriptParameters=ams_import.set
Symbol=USDJPY
Period=H1
ShutdownTerminal=1
EOF
mkdir -p "$MT5/MQL5/Presets"
printf 'InpFile=%s\r\nInpSymbol=%s\r\nInpOrigin=USDJPY\r\nInpSpreadPts=%s\r\n' \
  "$(basename "$CSV")" "$SYMBOL" "$SPREAD_PTS" > "$MT5/MQL5/Presets/ams_import.set"
echo "== 1/2 データ取り込み: $(basename "$CSV") → $SYMBOL =="
( cd "$MT5" && timeout 1800 xvfb-run -a wine terminal64.exe /portable /config:"ams_import.ini" ) || true
wineserver -w || true
LATEST_TERM=$(ls -t "$MT5"/logs/*.log 2>/dev/null | head -1)
utf16_to_utf8 "$LATEST_TERM" | grep "AMS-Import" | tail -3 || true

# 2) テスター実行（ログイン不要）
cat > "$MT5/ams_tester.ini" <<EOF
[Tester]
Expert=AdaptiveMultiStrategyEA.ex5
Symbol=$SYMBOL
Period=H1
Model=1
Optimization=0
FromDate=$FROM_DATE
ToDate=$TO_DATE
ForwardMode=0
Deposit=1000000
Currency=JPY
Leverage=1:25
ExecutionMode=0
Visual=0
Report=reports\\AMS_${SYMBOL}_H1
ReplaceReport=1
ShutdownTerminal=1
EOF
mkdir -p "$MT5/reports"
rm -f "$MT5/reports/AMS_${SYMBOL}_H1".*
echo "== 2/2 バックテスト: $SYMBOL H1 $FROM_DATE 〜 $TO_DATE =="
( cd "$MT5" && timeout "${BACKTEST_TIMEOUT:-5400}" xvfb-run -a wine terminal64.exe /portable /config:"ams_tester.ini" ) || true
wineserver -w || true

OUT="$REPO_ROOT/reports"; found=0
for f in "$MT5/reports/AMS_${SYMBOL}_H1".*; do
  [[ -f "$f" ]] || continue; cp "$f" "$OUT/"; found=1
done
COMMON_FILES=$(ls -d "$WINEPREFIX"/drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files 2>/dev/null | head -1 || true)
[[ -n "$COMMON_FILES" && -f "$COMMON_FILES/AMS_breakdown.csv" ]] && utf16_to_utf8 "$COMMON_FILES/AMS_breakdown.csv" > "$OUT/AMS_breakdown.csv"
LATEST_TERM=$(ls -t "$MT5"/logs/*.log 2>/dev/null | head -1 || true)
[[ -n "$LATEST_TERM" ]] && utf16_to_utf8 "$LATEST_TERM" > "$OUT/terminal_last.log"
LATEST_AGENT=$(find "$MT5/Tester" -path "*/logs/*.log" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || true)
[[ -n "$LATEST_AGENT" ]] && utf16_to_utf8 "$LATEST_AGENT" > "$OUT/tester_last.log"

if [[ $found -eq 0 ]]; then
  echo "NG: レポートが作られませんでした。reports/terminal_last.log と reports/tester_last.log を確認してください。" >&2
  exit 1
fi
echo "OK: レポートを $OUT に保存しました"
python3 "$REPO_ROOT/tools/summarize_report.py" "$OUT" || true
