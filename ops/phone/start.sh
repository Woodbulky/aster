#!/data/data/com.termux/files/usr/bin/bash
# Run from TERMUX (not inside Ubuntu). Starts the backend (inside proot Ubuntu) and the Cloudflare tunnel in tmux.
set -euo pipefail
ENV_FILE="$HOME/.aster.env"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"
TUNNEL_MODE="${TUNNEL_MODE:-named}"
TUNNEL_NAME="${TUNNEL_NAME:-aster}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

termux-wake-lock 2>/dev/null || true
tmux kill-session -t aster-api 2>/dev/null || true
tmux kill-session -t aster-tunnel 2>/dev/null || true

tmux new-session -d -s aster-api \
  "proot-distro login ubuntu -- bash -lc 'cd /root/aster/backend && /root/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 2>&1 | tee -a /root/aster-api.log'"

if [ "$TUNNEL_MODE" = "named" ]; then
  tmux new-session -d -s aster-tunnel "cloudflared tunnel --no-autoupdate run $TUNNEL_NAME"
else
  tmux new-session -d -s aster-tunnel "bash $SCRIPT_DIR/quick_tunnel.sh"
fi

echo "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    curl -s http://127.0.0.1:8000/health; echo; break
  fi
  sleep 2
done
echo "Sessions: tmux attach -t aster-api   |   tmux attach -t aster-tunnel   (detach: Ctrl-b d)"
