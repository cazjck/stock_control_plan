#!/usr/bin/env bash
# Triển khai lên web-01 (192.168.1.20, user pdk) không cần root:
#   - code: git clone/pull nhánh main từ GitHub trên web-01
#   - giao diện: build ở máy này rồi rsync frontend/dist (web-01 chỉ có 2,8 GB RAM)
#   - backend: venv + requirements.txt, dịch vụ systemd cấp user, nghe 127.0.0.1:8010
#   - lần đầu (--init): chép backend/data và tạo backend/.env có APP_ACCESS_TOKEN ngẫu nhiên
# Không bao giờ ghi đè .env hay data đã có trên máy chủ.
set -euo pipefail

HOST="${HOST:-pdk@192.168.1.20}"
DIR="${DIR:-apps/stock_control_plan}"
REPO="${REPO:-https://github.com/cazjck/stock_control_plan.git}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INIT=0
[ "${1:-}" = "--init" ] && INIT=1

echo "== build giao diện"
(cd "$ROOT/frontend" && npm run build >/dev/null)

echo "== code trên $HOST:~/$DIR"
ssh "$HOST" "set -e; if [ -d ~/$DIR/.git ]; then git -C ~/$DIR fetch -q origin main && git -C ~/$DIR checkout -q main && git -C ~/$DIR reset -q --hard origin/main; else mkdir -p ~/apps && git clone -q --branch main $REPO ~/$DIR; fi; git -C ~/$DIR log --oneline -1"
rsync -az --delete "$ROOT/frontend/dist/" "$HOST:$DIR/frontend/dist/"

if [ "$INIT" = 1 ]; then
  echo "== lần đầu: dữ liệu và .env"
  ssh "$HOST" "test ! -e ~/$DIR/backend/.env" || { echo "Đã có .env trên máy chủ, không ghi đè"; exit 1; }
  rsync -az "$ROOT/backend/data/" "$HOST:$DIR/backend/data/"
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  # .env của máy này, đổi DATA_DIR và đặt mã truy cập; chỉ chủ file đọc được
  sed -e "s|^DATA_DIR=.*|DATA_DIR=data|" -e "s|^APP_ACCESS_TOKEN=.*|APP_ACCESS_TOKEN=$TOKEN|" "$ROOT/backend/.env" \
    | ssh "$HOST" "umask 077; cat > ~/$DIR/backend/.env; chmod 700 ~/$DIR/backend/data"
  unset TOKEN
fi

echo "== backend"
ssh "$HOST" "set -e; cd ~/$DIR && REQS=requirements.txt ./scripts/setup-backend.sh
  mkdir -p ~/.config/systemd/user && cp deploy/stockctl.service ~/.config/systemd/user/stockctl.service
  systemctl --user daemon-reload && systemctl --user enable -q stockctl.service && systemctl --user restart stockctl.service
  for i in \$(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:8010/api/health && break; sleep 1; done
  systemctl --user is-active stockctl.service; curl -s http://127.0.0.1:8010/api/health; echo"
echo "Xong. Mã truy cập: ssh $HOST grep APP_ACCESS_TOKEN ~/$DIR/backend/.env"
