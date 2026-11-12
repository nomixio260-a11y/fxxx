#!/usr/bin/env bash
# ストラテジーテスターを画面なし（Xvfb）で実行し、レポートを reports/ に保存する。
#   bash tools/backtest.sh [開始日 YYYY.MM.DD] [終了日 YYYY.MM.DD]
# ログイン情報は tester/credentials.env（git 管理外）か、環境変数
#   MT5_LOGIN / MT5_PASSWORD / MT5_SERVER / MT5_SYMBOL で渡す。
set -euo pipefail
source "$(dirname "$0")/common.sh"

MT5=$(find_mt5_dir) || { echo "ERROR: MT5 が見つかりません。先に tools/install_mt5.sh を実行してください。" >&2; exit 1; }

CRED="$REPO_ROOT/tester/credentials.env"
if [[ -f "$CRED" ]]; then
  set -a; source "$CRED"; set +a
fi
: "${MT5_LOGIN:?MT5_LOGIN が未設定です（tester/credentials.env を作成してください）}"
: "${MT5_PASSWORD:?MT5_PASSWORD が未設定です}"
: "${MT5_SERVER:?MT5_SERVER が未設定です}"
MT5_SYMBOL="${MT5_SYMBOL:-USDJPY}"

TO_DATE="${2:-$(date +%Y.%m.%d)}"
FROM_DATE="${1:-$(date -d '2 years ago' +%Y.%m.%d)}"

# 最新のソースでコンパイルしてから実行
bash "$REPO_ROOT/tools/compile.sh" >/dev/null

# 設定ファイルを作成（パスワードを含むので、終了時に必ず削除）
CONF="$MT5/ams_tester.ini"
trap 'rm -f "$CONF"' EXIT
# パスワードに記号が含まれても壊れないよう、置換は Python で行う
export MT5_LOGIN MT5_PASSWORD MT5_SERVER MT5_SYMBOL FROM_DATE TO_DATE
python3 - "$REPO_ROOT/tester/USDJPY_H1.ini" "$CONF" <<'PY'
import os, sys
text = open(sys.argv[1], encoding="utf-8").read()
for key in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_SYMBOL", "FROM_DATE", "TO_DATE"):
    text = text.replace("{{%s}}" % key, os.environ[key])
# テスターの設定ファイルは Windows の改行で書く
open(sys.argv[2], "w", encoding="utf-8", newline="\r\n").write(text)
PY
mkdir -p "$MT5/reports"
rm -f "$MT5/reports/AMS_${MT5_SYMBOL}_H1".*

echo "== バックテスト実行: $MT5_SYMBOL H1 $FROM_DATE 〜 $TO_DATE（サーバー: $MT5_SERVER）=="
echo "   履歴データのダウンロードがあるため、初回は時間がかかります。"
( cd "$MT5" && timeout "${BACKTEST_TIMEOUT:-5400}" xvfb-run -a wine terminal64.exe /portable /config:"ams_tester.ini" ) || true
wineserver -w || true

OUT="$REPO_ROOT/reports"
mkdir -p "$OUT"
found=0
for f in "$MT5/reports/AMS_${MT5_SYMBOL}_H1".*; do
  [[ -f "$f" ]] || continue
  cp "$f" "$OUT/"
  found=1
done

# EA が出力した相場状況別・ロジック別の成績
COMMON_FILES=$(ls -d "$WINEPREFIX"/drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files 2>/dev/null | head -1 || true)
if [[ -n "$COMMON_FILES" && -f "$COMMON_FILES/AMS_breakdown.csv" ]]; then
  utf16_to_utf8 "$COMMON_FILES/AMS_breakdown.csv" > "$OUT/AMS_breakdown.csv"
fi

# ログ（パスワードは含まれない）
#   terminal_last.log : ターミナルのログ（ログイン・履歴ダウンロード）
#   tester_last.log   : テスターエージェントのログ（EA の Print 出力・注文結果）
LATEST_TERM=$(ls -t "$MT5"/logs/*.log 2>/dev/null | head -1 || true)
[[ -n "$LATEST_TERM" ]] && utf16_to_utf8 "$LATEST_TERM" > "$OUT/terminal_last.log"
LATEST_AGENT=$(find "$MT5/Tester" -path "*/logs/*.log" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || true)
[[ -n "$LATEST_AGENT" ]] && utf16_to_utf8 "$LATEST_AGENT" > "$OUT/tester_last.log"

if [[ $found -eq 0 ]]; then
  echo "NG: レポートが作られませんでした。reports/tester_last.log と $MT5/logs を確認してください。" >&2
  echo "    よくある原因: ログイン失敗、サーバーに接続できない、銘柄名の違い（接尾辞）。" >&2
  exit 1
fi
echo "OK: レポートを $OUT に保存しました"
python3 "$REPO_ROOT/tools/summarize_report.py" "$OUT" || true
