#!/usr/bin/env bash
# Linux（Ubuntu 22.04/24.04）に Wine + Xvfb + MetaTrader 5 を入れる。
# 使い方:  sudo なしで root の場合はそのまま / 一般ユーザーは apt 部分に sudo が必要
#   bash tools/install_mt5.sh
# 環境変数:
#   MT5_INSTALLER_URL  インストーラーのURL（既定: MetaQuotes 公式 mt5setup.exe）
#                      OANDA 版を使う場合は OANDA のサイトにある MT5 インストーラーの URL を指定
#   WINEPREFIX         Wine の環境（既定: ~/.mt5）
set -euo pipefail
source "$(dirname "$0")/common.sh"

MT5_INSTALLER_URL="${MT5_INSTALLER_URL:-https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe}"
SUDO=""
[[ $(id -u) -ne 0 ]] && SUDO="sudo"

echo "== 1/3 Wine と Xvfb の導入 =="
if ! command -v wine >/dev/null || ! command -v xvfb-run >/dev/null; then
  $SUDO dpkg --add-architecture i386
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq \
    wine64 wine32:i386 xvfb xauth winbind cabextract
fi
wine --version

echo "== 2/3 Wine 環境の作成 ($WINEPREFIX) =="
if [[ ! -d "$WINEPREFIX/drive_c" ]]; then
  xvfb-run -a wineboot --init
  wineserver -w
fi
# MT5 は Windows 10 として動かす
xvfb-run -a wine reg add 'HKEY_CURRENT_USER\Software\Wine' /v Version /t REG_SZ /d win10 /f >/dev/null
wineserver -w

echo "== 3/3 MetaTrader 5 のインストール =="
if MT5=$(find_mt5_dir); then
  echo "インストール済み: $MT5"
  exit 0
fi

DL_DIR="$(mktemp -d)"
INSTALLER="$DL_DIR/mt5setup.exe"
echo "ダウンロード: $MT5_INSTALLER_URL"
if ! curl -fSL --retry 3 -o "$INSTALLER" "$MT5_INSTALLER_URL"; then
  echo "ERROR: インストーラーをダウンロードできませんでした。" >&2
  echo "       ネットワーク制限で download.mql5.com などが許可されていない可能性があります。" >&2
  exit 2
fi

# /auto で自動インストール。インストール後にターミナルが起動するので、終わったら止める
xvfb-run -a wine "$INSTALLER" /auto &
INST_PID=$!
for _ in $(seq 1 180); do
  if MT5=$(find_mt5_dir); then
    sleep 20   # 残りのファイル展開を待つ
    break
  fi
  sleep 5
done
wineserver -k || true
wait "$INST_PID" 2>/dev/null || true
rm -rf "$DL_DIR"

if MT5=$(find_mt5_dir); then
  echo "インストール完了: $MT5"
else
  echo "ERROR: terminal64.exe が見つかりません。インストールに失敗しました。" >&2
  exit 3
fi
