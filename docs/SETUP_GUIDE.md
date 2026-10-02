# Aster — Setup Guide (do these in order)

**Order:** accounts → repo + Claude Code → Supabase (+ MCP) → Kaggle GPU → (optional) phone backup → build with Claude Code → backend on Render → Vercel → demo day.

Why this order: Supabase must exist before the GPU worker can register its URL. The GPU is the riskiest piece, so prove it on day 1. You develop the backend on your laptop; Render deploys it from `main` (a manual web service; `render.yaml` mirrors its settings). The phone is only an optional backup host.

---

## Phase 0 — Accounts & keys (day 1; apply for Bhashini FIRST — approval can take time)

| Service | Where | What you copy | Goes into |
|---|---|---|---|
| GitHub | github.com → New repository `aster` (private) | repo URL | git |
| Supabase | supabase.com | project ref, URL, anon/publishable key, secret/service key, DB password | `.env` files, MCP |
| Kaggle | kaggle.com | — (phone-verify the account) | notebook |
| Hugging Face | huggingface.co/settings/tokens → Read token | `HF_TOKEN` | Kaggle Secrets |
| Sarvam AI | dashboard.sarvam.ai → API keys | `SARVAM_API_KEY` | backend `.env` |
| Bhashini | bhashini.gov.in → register on ULCA | `userID`, `ulcaApiKey` | backend `.env` |
| Tavily | app.tavily.com | `TAVILY_API_KEY` | backend `.env` |
| Fallback LLM | any OpenAI-compatible provider with a vision model (e.g. Gemini's OpenAI-compatible endpoint, Groq, OpenRouter) | base URL, key, model | backend `.env` |
| Render | render.com (login with GitHub) | — | backend deploy |
| Cloudflare (optional) | dash.cloudflare.com (+ a domain if you have one) | — | phone backup |
| Vercel | vercel.com (login with GitHub) | — | web deploy |

Generate two random secrets on your laptop and save them in a password manager:
```bash
python3 -c "import secrets; print('GATEWAY_TOKEN=' + secrets.token_urlsafe(32)); print('GPU_REGISTER_SECRET=' + secrets.token_urlsafe(32))"
```

---

## Phase 1 — Repo + Claude Code (laptop)

1. Install the tools:
   - Node.js LTS from nodejs.org, then `corepack enable` (gives you `pnpm`).
   - uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (Windows: see docs.astral.sh/uv).
   - Git.
   - Claude Code: follow docs.claude.com/en/docs/claude-code/overview (native installer or `npm install -g @anthropic-ai/claude-code`).
2. Clone the empty repo and copy this context pack into its root:
   ```bash
   git clone https://github.com/<you>/aster.git && cd aster
   # copy everything from the pack here: CLAUDE.md, docs/, supabase/, gpu/, knowledge/, ops/, .claude/, backend/, web/
   git add . && git commit -m "chore: Aster context pack" && git push
   ```
3. Start Claude Code in the repo root with `claude`. Ask: `Summarise CLAUDE.md in 5 lines.` This checks that it reads the context.

---

## Phase 2 — Supabase

### 2.1 Create the project
1. supabase.com → New project. Name `aster`. Region: **South Asia (Mumbai)**. Set a strong DB password and save it.
2. Project Settings → General → copy the **Project ref**. It's also in the URL `supabase.com/dashboard/project/<ref>`.
3. Project Settings → API Keys → copy the **anon / publishable** key (for the web) and the **secret / service_role** key (backend only — never in `web/`).

### 2.2 Auth settings
1. Authentication → Sign In / Providers → **Email** enabled.
2. Authentication → URL Configuration → Site URL `http://localhost:3000`. Add redirect URL `http://localhost:3000/**` now; add the Vercel URL later.
3. ⚠️ Supabase's built-in email sender is heavily rate-limited (a few emails per hour). Before testing with your team, do one of these:
   - (a) Enable **Google** provider: Google Cloud Console → OAuth client (Web) → authorised redirect URI = the callback URL Supabase shows → paste the client ID/secret into Supabase.
   - (b) Set custom SMTP (e.g. Resend free tier) under Authentication → Emails → SMTP.

### 2.3 Connect the Supabase MCP to Claude Code
Use a **dev** project only, never one with real user data. In the repo root:
```bash
claude mcp add --scope project --transport http supabase "https://mcp.supabase.com/mcp?project_ref=<PROJECT_REF>&features=docs,database,debugging,development"
```
Then:
1. Run `claude`, type `/mcp`, select **supabase** → **Authenticate**. A browser opens; log in and allow your org.
2. Check it: `claude mcp list` should show supabase connected.
3. Commit the generated `.mcp.json`. It contains no secrets, only the URL.

(Leave out `read_only=true` because Claude Code must apply migrations. Supabase's current options: supabase.com/docs/guides/ai-tools/mcp.)

### 2.4 Apply the schema (via Claude Code)
Paste into Claude Code:
```
Using the Supabase MCP, apply supabase/migrations/0001_init.sql with apply_migration (name "0001_init").
Then list all tables, confirm RLS is enabled on each, confirm the "documents" storage bucket exists,
run the security and performance advisors, and report findings. Do not change anything else.
```

### 2.5 Set the registration secret (manually, so it isn't in any transcript)
Supabase → SQL Editor → run:
```sql
insert into public.gpu_secrets (id, secret) values (1, '<GPU_REGISTER_SECRET>')
on conflict (id) do update set secret = excluded.secret;
```

### 2.6 Verify
- Table Editor shows: profiles, assistant_settings, form_sessions, messages, documents, field_values, flags, … plus gpu_endpoints and public_endpoints.
- Storage shows the private bucket `documents`.

---

## Phase 3 — Kaggle GPU worker

You don't download the model yourself. Cell 5 of the notebook makes Ollama pull `qwen3-vl:8b-instruct` (~6 GB; the plain `8b` tag thinks before answering and `/v1` cannot turn that off) into the session every time it starts, which takes a few minutes.

1. **Verify your phone number**: kaggle.com → your profile → Settings → Phone verification. GPU and Internet stay locked without it.
2. **Hugging Face**: open `huggingface.co/ai4bharat/indic-conformer-600m-multilingual` → accept the terms (gated model). Create a Read token.
3. **Import the notebook**: Kaggle → Create → New Notebook → File → **Import Notebook** → upload `gpu/aster_gpu_worker.ipynb`.
4. **Notebook settings** (right sidebar): Accelerator → **GPU T4 x2**; Internet → **On**.
5. **Secrets**: Add-ons → Secrets → add each one and tick it so it is attached to this notebook:
   - `GATEWAY_TOKEN`
   - `HF_TOKEN`
   - `SUPABASE_URL` (`https://<ref>.supabase.co`)
   - `SUPABASE_ANON_KEY` (anon/publishable key)
   - `GPU_REGISTER_SECRET`
6. **First run**: run the cells top to bottom, one at a time, and read each output.

   | Cell | Expect |
   |---|---|
   | 2 `nvidia-smi` | two Tesla T4, ~15 GB each |
   | 3 install | Ollama + cloudflared versions printed |
   | 4 start Ollama | `✅ Ollama ready on GPU 0` |
   | 5 pull | download progress, then the model in `ollama list` |
   | 6 warm-up | a Marathi sentence, the load time, and `Tool calls: [...]` (if None, tool calling needs prompt work — tell Claude Code in M2) |
   | 7 gateway | `Warmup: {'ocr': 'ok', 'asr': 'ok'}` — if ASR says a package is missing, `pip install` it in a new cell and rerun cell 7 |
   | 8 tunnel | `Public gateway: https://xxxx.trycloudflare.com` |
   | 9 register | `Registered: True` |
   | 10 test | a Marathi reply + round-trip time + `✅ No-token request rejected: 401` |
   | 11 keep-alive | a status line every minute (leave it running) |

7. **Check from your laptop**:
   ```bash
   curl https://xxxx.trycloudflare.com/health
   curl -H "Authorization: Bearer <GATEWAY_TOKEN>" https://xxxx.trycloudflare.com/v1/models
   ```
   In Supabase Table Editor, `gpu_endpoints` should have row `kaggle-main` with a fresh `last_seen`.
8. **Save quota**: when you're not testing, stop the session with the power button in the notebook toolbar. GPU hours are limited per week (the quota is shown in Kaggle). During development, use the fallback LLM and run Kaggle only when testing GPU features.
9. **Demo day**: Save Version → **Save & Run All (Commit)**. It runs headless for up to about 12 hours with no browser needed. Start it about 1 hour before judging.

---

## Phase 4 — Phone server (optional backup) (OnePlus Nord 2T: Termux + proot Ubuntu)

**Optional backup.** The backend runs on Render (Phase 5b). Set up the phone only if you want a fallback host for the demo.

⚠️ n8n already runs a Cloudflare tunnel on this phone and may use `~/.cloudflared/config.yml`. Aster's tunnel uses its own file `~/.cloudflared/aster.yml` — never touch `config.yml`.

### 4.1 Android settings (so Android doesn't kill the server)
1. Settings → Apps → Termux → Battery → **Unrestricted / Don't optimise** and allow background activity (OxygenOS label names vary).
2. Open Recents, long-press the Termux card → **Lock**.
3. Keep the phone on a charger during demos, with a fan or a cool surface (it throttles when hot).
4. **Phantom process killer.** Android 12+ kills Termux child processes, and the symptom is the server dying randomly after minutes. Check your Android version in Settings → About phone.
   - **Android 14+**: Settings → About → tap Build number 7× → Developer options → enable **"Disable child process restrictions"**.
   - **Android 12/13**: enable USB debugging in Developer options, connect to the laptop with platform-tools `adb` installed, and run:
     ```bash
     adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
     adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
     adb shell settings put global settings_enable_monitor_phantom_procs false
     ```

### 4.2 Termux base (in Termux, not Ubuntu)
```bash
pkg update && pkg upgrade -y
pkg install -y proot-distro tmux openssh cloudflared git curl nano
termux-wake-lock          # also available from the Termux notification
proot-distro list         # ubuntu should show as installed; if not: proot-distro install ubuntu
```
If `pkg install cloudflared` fails, install the arm64 `.deb` inside Ubuntu instead (step 4.4) and run cloudflared there.

### 4.3 SSH from your laptop (recommended — typing on the phone is painful)
In Termux:
```bash
passwd            # set a password
whoami            # note the username (like u0_a123)
sshd              # starts on port 8022
ip addr | grep inet    # find the phone's Wi-Fi IP (192.168.x.x)
```
On the laptop: `ssh -p 8022 <username>@<phone-ip>` (both devices on the same Wi-Fi).

### 4.4 Ubuntu environment
```bash
proot-distro login ubuntu
# now inside Ubuntu (prompt shows root@localhost)
apt update && apt upgrade -y
apt install -y curl git ca-certificates build-essential ffmpeg tmux nano
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
uv --version
uv python install 3.12
```

### 4.5 Get the code onto the phone (inside Ubuntu)
1. GitHub → Settings → Developer settings → Fine-grained token: repo `aster`, Contents: Read-only.
2. Then:
   ```bash
   cd /root
   git clone https://github.com/<you>/aster.git     # username + token as password
   git config --global credential.helper store            # remember it for git pull
   cd aster/backend
   cp .env.example .env && nano .env                      # fill the values (same as laptop)
   ```
   Before M0 exists, test the tunnel with a dummy server instead: `cd /root && python3 -m http.server 8000`.
3. After M0+: `uv sync && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`, then in another Termux session `curl http://127.0.0.1:8000/health`.

### 4.6 Expose the backend with Cloudflare (in Termux)

**Option A — stable URL (recommended; needs a domain on Cloudflare).** Add the domain to Cloudflare and switch its nameservers at your registrar. Then in Termux:
```bash
ls ~/.cloudflared/cert.pem || cloudflared tunnel login   # skip login if cert.pem exists (n8n set it up)
cloudflared tunnel create aster              # note the tunnel UUID; creates ~/.cloudflared/<UUID>.json
cloudflared tunnel route dns aster api.<yourdomain>
cp <path-to-repo>/ops/phone/cloudflared-aster.yml ~/.cloudflared/aster.yml   # NOT config.yml
nano ~/.cloudflared/aster.yml                    # put the UUID + hostname
cloudflared tunnel --config ~/.cloudflared/aster.yml ingress validate
cloudflared tunnel --config ~/.cloudflared/aster.yml run aster
```
Test from the laptop: `curl https://api.<yourdomain>/health`. To fail over to the phone, set `NEXT_PUBLIC_API_URL=https://api.<yourdomain>` in web env.

**Option B — no domain (quick tunnel + auto-registration).** The URL changes on every restart, so the script registers it in Supabase `public_endpoints` and the web app discovers it. To fail over to it, set `NEXT_PUBLIC_API_URL` empty.

The repo lives inside Ubuntu. From Termux, its path is:
`$PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu/root/aster`

### 4.7 One-command start (in Termux)
```bash
cat > ~/.aster.env << 'ENV'
TUNNEL_MODE=named            # or: quick
TUNNEL_NAME=aster
TUNNEL_CONFIG=$HOME/.cloudflared/aster.yml
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon key>
GPU_REGISTER_SECRET=<secret>
ENV
echo 'alias aster="bash $PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu/root/aster/ops/phone/start.sh"' >> ~/.bashrc
source ~/.bashrc
aster                   # starts API + tunnel in tmux sessions aster-api and aster-tunnel
tmux ls                 # see sessions;  tmux attach -t aster-api  (detach: Ctrl-b then d)
```

### 4.8 Update after new commits
```bash
proot-distro login ubuntu -- bash -lc "cd /root/aster && git pull && cd backend && uv sync"
aster  # restarts both sessions
```

---

## Phase 5 — Build with Claude Code
In the repo root, run `claude`, then:
```
/status
/milestone M0
```
Approve the plan, let it build, check the evidence, commit, then `/milestone M1` and so on. Rules of thumb:
- One milestone per session. Run `/clear` between milestones to keep context clean.
- Before M2, start the Kaggle notebook. Before M4, have the Sarvam/Bhashini keys. Before M5, have Tavily, and the team must verify the knowledge packs (Claude Code will stop and ask).
- If Claude Code drifts from the specs, say: "Re-read CLAUDE.md and docs/<X>.md and fix the deviation."

## Phase 5b — Backend on Render (after M0)
Live service: `https://aster-jj5b.onrender.com` (created manually, not via Blueprint).
1. render.com → **New → Web Service** → connect GitHub → pick the `aster` repo, branch `main`.
2. Settings: Language **Python 3**, Root Directory `backend`, Region **Singapore**, Instance type **Free**.
   - Build command: `pip install uv && uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt && pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`. Auto-Deploy: **On Commit**.
   - Python 3.12 comes from `backend/.python-version` (Render's default is 3.14). Check the build log says 3.12.
3. Environment: add the keys from `backend/.env.example` (same values as your laptop `.env`). Secrets stay in Render, never in git. `/health` needs none of them; blank values fall back to defaults.
4. Deploy, then check: `curl https://aster-jj5b.onrender.com/health` → `{"status":"ok","version":...}`.
5. Every push to `main` redeploys automatically. `render.yaml` is a reference copy of these settings (New → Blueprint can recreate the service); editing it does **not** change the live service — change the dashboard and keep `render.yaml` in sync.
5. ⚠️ The free plan sleeps after ~15 min idle (first request then takes ~1 min). Before judging: set up a keep-warm pinger on `/health` every ~10 min (e.g. a free uptime monitor), or switch to the Starter plan for demo week.

## Phase 6 — Deploy the web app (after M1, redeploy anytime)
1. Vercel → Add New Project → import `aster` → Root Directory = `web`.
2. Environment variables: copy from `web/.env.local.example`; set `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`.
3. Deploy. Then add `https://<project>.vercel.app/**` to Supabase redirect URLs and `ALLOWED_ORIGINS` in the Render env vars (and backend `.env`).

## Phase 7 — Demo-day runbook
- [ ] T-60 min: Kaggle → Save & Run All. Check `gpu_endpoints.last_seen` is fresh.
- [ ] T-45: `curl https://<service>.onrender.com/health` shows all providers up (keep-warm pinger running). Backup: phone on charger, run `aster`, `curl https://api.../health`.
- [ ] T-30: log in with the demo account on the laptop (Chrome) and the phone; mic permission granted; portal tab ready.
- [ ] T-15: full dry run of the demo script; backup video ready.
- [ ] Fallback drill done earlier: stop Kaggle → Aster still answers (fallback LLM + Sarvam).
