#!/usr/bin/env bash
# histdata.com から 1分足（ASCII, EST 固定時刻）をダウンロードして 1つの CSV にまとめる。
#   bash tools/fetch_histdata.sh USDJPY 2024 2026 [出力先CSV]
# 完了した年は年単位、今年は月単位で取得する。
# 出力形式: YYYY.MM.DD,HH:MM,open,high,low,close,volume（時刻は EST+7h = 東欧時間相当に変換済み）
set -euo pipefail
PAIR="${1:-USDJPY}"; FROM_Y="${2:-2024}"; TO_Y="${3:-$(date +%Y)}"
OUT="${4:-$(cd "$(dirname "$0")/.." && pwd)/data/${PAIR}_M1.csv}"
LOWER=$(echo "$PAIR" | tr 'A-Z' 'a-z')
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
mkdir -p "$(dirname "$OUT")"

fetch() {  # $1=year  $2=month(空なら年単位)
  local y="$1" m="${2:-}" url
  url="https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/$LOWER/$y${m:+/$((10#$m))}"
  curl -fsS -c "$WORK/cj" -b "$WORK/cj" -o "$WORK/page.html" "$url" || return 1
  local tk; tk=$(grep -oE 'name="tk" id="tk" value="[^"]+"' "$WORK/page.html" | head -1 | sed 's/.*value="//; s/"$//')
  [[ -n "$tk" ]] || return 1
  curl -fsS -c "$WORK/cj" -b "$WORK/cj" -e "$url" -o "$WORK/$y$m.zip" \
    --data "tk=$tk&date=$y&datemonth=$y$m&platform=ASCII&timeframe=M1&fxpair=$PAIR" \
    "https://www.histdata.com/get.php" || return 1
  unzip -p "$WORK/$y$m.zip" '*.csv' >> "$WORK/all.csv" 2>/dev/null || return 1
  echo "取得: $PAIR $y${m:+-$m}"
}

CUR_Y=$(date +%Y); CUR_M=$(date +%m)
for y in $(seq "$FROM_Y" "$TO_Y"); do
  if [[ "$y" -lt "$CUR_Y" ]] && fetch "$y"; then continue; fi
  for m in $(seq -w 1 12); do
    [[ "$y" -eq "$CUR_Y" && $((10#$m)) -ge $((10#$CUR_M)) ]] && break
    fetch "$y" "$m" || echo "なし: $PAIR $y-$m"
  done
done

# histdata の形式: 20240102 170000;open;high;low;close;vol （EST、夏時間なし）
# MT5 の一般的なサーバー時間（東欧時間）に近づけるため +7 時間する
python3 - "$WORK/all.csv" "$OUT" <<'PY'
import sys, datetime
seen = set(); rows = []
for line in open(sys.argv[1], encoding="utf-8", errors="ignore"):
    p = line.strip().split(";")
    if len(p) < 6: continue
    try:
        t = datetime.datetime.strptime(p[0], "%Y%m%d %H%M%S") + datetime.timedelta(hours=7)
    except ValueError:
        continue
    if t in seen: continue
    seen.add(t); rows.append((t, p[1], p[2], p[3], p[4], p[5]))
rows.sort()
with open(sys.argv[2], "w") as f:
    for t, o, h, l, c, v in rows:
        f.write(f"{t:%Y.%m.%d,%H:%M},{o},{h},{l},{c},{v}\n")
print(f"{len(rows)} 本 → {sys.argv[2]}  ({rows[0][0]} 〜 {rows[-1][0]})")
PY
