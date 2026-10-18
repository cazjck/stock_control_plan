#!/usr/bin/env bash
# Kéo các bản sao lưu SQLite từ web-01 về dev-01 (bản sao thứ hai, ngoài máy chủ). Giữ 60 bản trên dev-01.
set -euo pipefail
HOST="${HOST:-pdk@192.168.1.20}"
SRC="${SRC:-apps/stock_control_plan/backend/data/backups/}"
DEST="${DEST:-$HOME/backups/stock_control_plan}"
mkdir -p "$DEST" && chmod 700 "$DEST"
rsync -a --chmod=F600 "$HOST:$SRC" "$DEST/"
ls -1 "$DEST"/stockctl-*.sqlite 2>/dev/null | head -n -60 | xargs -r rm -f
echo "$(date -Is) $(ls "$DEST" | wc -l) bản tại $DEST"
