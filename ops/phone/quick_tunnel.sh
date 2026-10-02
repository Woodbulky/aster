#!/data/data/com.termux/files/usr/bin/bash
# Quick tunnel (no domain). Registers the changing URL in Supabase public_endpoints('api') and refreshes it every 2 min.
set -uo pipefail
source "$HOME/.aster.env"
LOG="${PREFIX:-/tmp}/tmp/aster_quick_tunnel.log"
mkdir -p "$(dirname "$LOG")"; : > "$LOG"

cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000 >"$LOG" 2>&1 &
CF_PID=$!

URL=""
for i in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -n1 || true)
  [ -n "$URL" ] && break
  sleep 1
done
[ -z "$URL" ] && { echo "No tunnel URL. See $LOG"; kill $CF_PID 2>/dev/null; exit 1; }
echo "Public API: $URL"

register() {
  curl -s -o /dev/null -w "register: %{http_code}\n" -X POST "$SUPABASE_URL/rest/v1/rpc/register_public_endpoint" \
    -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" -H "Content-Type: application/json" \
    -d "{\"p_secret\":\"$GPU_REGISTER_SECRET\",\"p_name\":\"api\",\"p_url\":\"$URL\"}"
}

while kill -0 $CF_PID 2>/dev/null; do
  register
  sleep 120
done
echo "cloudflared exited"
