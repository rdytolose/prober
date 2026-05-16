#!/usr/bin/env bash
# =====================================================================
#  VPN Prober — one-shot installer for Ubuntu 22.04 / 24.04
# =====================================================================
#  Usage:
#    bash scripts/install.sh --role coordinator [--domain HOST --email YOU@DOMAIN]
#    bash scripts/install.sh --role prober      [--prober-name NAME --coordinator-url URL --prober-token TOKEN]
#
#  Steps it performs:
#    1. Installs Docker Engine + compose-plugin from the official repo
#    2. Configures ufw (opens 22, plus 80/443 on coordinator side)
#    3. Generates .env (or keeps existing one) with random tokens
#    4. docker compose up -d --build for the selected role
#    5. Prints the dashboard URL + tokens + a copy-paste command
#       to install the prober on the other VPS.
#
#  Re-running the script is safe (idempotent).  Existing .env is kept
#  unless you pass --overwrite-env.
# =====================================================================
set -euo pipefail

# ---------- helpers ----------
log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ ok ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

ROLE=""
DOMAIN=""
EMAIL=""
ADMIN_TOKEN=""
PROBER_TOKENS=""
NO_TLS=0
PROBER_NAME=""
COORDINATOR_URL=""
PROBER_TOKEN=""
ASSUME_YES=0
OVERWRITE_ENV=0

usage() {
  cat <<'EOF'
Usage:
  install.sh --role coordinator [options]
  install.sh --role prober      [options]

General:
  --role coordinator|prober   What to install on this server.
  --yes                       Don't ask for confirmation prompts.
  --overwrite-env             Replace existing .env (otherwise it is kept).

Coordinator-side options:
  --domain HOST               Domain pointing to this VPS, e.g. coordinator.example.com.
  --email YOU@DOMAIN          Email for Let's Encrypt registration.
  --admin-token TOKEN         (optional) admin token; auto-generated if omitted.
  --prober-tokens T1,T2,...   (optional) comma-separated tokens that probers will use;
                              one random token is generated if omitted.
  --no-tls                    Skip Caddy + HTTPS, expose coordinator on :8080 (TESTING ONLY).

Prober-side options:
  --prober-name NAME          Unique label for this prober (e.g. de-1).
  --coordinator-url URL       Full URL of the coordinator, e.g. https://coordinator.example.com
  --prober-token TOKEN        One of the tokens listed on the coordinator side.

Examples:
  # Coordinator (asks for domain/email interactively if not provided)
  bash scripts/install.sh --role coordinator \
      --domain coordinator.example.com --email me@example.com

  # Prober
  bash scripts/install.sh --role prober \
      --prober-name de-1 \
      --coordinator-url https://coordinator.example.com \
      --prober-token <one-of-the-tokens-from-coordinator-install>
EOF
}

# ---------- arg parsing ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)             ROLE="$2";            shift 2 ;;
    --yes)              ASSUME_YES=1;         shift   ;;
    --overwrite-env)    OVERWRITE_ENV=1;      shift   ;;
    --domain)           DOMAIN="$2";          shift 2 ;;
    --email)            EMAIL="$2";           shift 2 ;;
    --admin-token)      ADMIN_TOKEN="$2";     shift 2 ;;
    --prober-tokens)    PROBER_TOKENS="$2";   shift 2 ;;
    --no-tls)           NO_TLS=1;             shift   ;;
    --prober-name)      PROBER_NAME="$2";     shift 2 ;;
    --coordinator-url)  COORDINATOR_URL="$2"; shift 2 ;;
    --prober-token)     PROBER_TOKEN="$2";    shift 2 ;;
    -h|--help)          usage; exit 0 ;;
    *) die "Unknown argument: $1 (use --help)" ;;
  esac
done

if [[ -z "$ROLE" ]]; then
  if [[ $ASSUME_YES -eq 1 ]]; then
    die "--role is required when --yes is set"
  fi
  echo "Select role to install on THIS server:"
  echo "  1) coordinator  — central server (dashboard + API)"
  echo "  2) prober       — worker that tests VPN/proxy links"
  read -rp "Enter 1 or 2: " sel
  case "$sel" in
    1) ROLE=coordinator ;;
    2) ROLE=prober ;;
    *) die "Invalid selection" ;;
  esac
fi

[[ "$ROLE" == "coordinator" || "$ROLE" == "prober" ]] \
  || die "--role must be 'coordinator' or 'prober'"

# ---------- sudo / OS check ----------
if [[ $EUID -eq 0 ]]; then
  SUDO=""
  warn "Running as root.  Recommend creating a non-root sudo user first."
else
  SUDO="sudo"
fi

if [[ ! -r /etc/os-release ]]; then
  die "Cannot detect OS — /etc/os-release missing.  This script supports Ubuntu 22.04 / 24.04."
fi
# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  warn "Tested only on Ubuntu (you have ${PRETTY_NAME:-unknown})."
  if [[ $ASSUME_YES -eq 0 ]]; then
    read -rp "Continue anyway? [y/N] " yn
    [[ "$yn" =~ ^[Yy]$ ]] || exit 1
  fi
fi

# Resolve project root (script lives in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -d "$PROJECT_ROOT/deploy/coordinator" ]] \
  || die "Project layout is wrong — $PROJECT_ROOT/deploy/coordinator not found."

# ---------- 1. apt + Docker ----------
log "[1/5] apt update + base packages"
$SUDO apt-get update -y
$SUDO apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg openssl ufw

if ! command -v docker >/dev/null 2>&1; then
  log "[2/5] installing Docker from the official repo"
  $SUDO install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
  ARCH="$(dpkg --print-architecture)"
  CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODENAME stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  $SUDO apt-get update -y
  $SUDO apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  if [[ $EUID -ne 0 ]]; then
    $SUDO usermod -aG docker "$USER" || true
    warn "Added '$USER' to the 'docker' group.  Log out & in for it to take effect."
    warn "For now, this script will keep using 'sudo docker'."
  fi
else
  log "[2/5] Docker already installed: $(docker --version)"
fi

COMPOSE="$SUDO docker compose"

# ---------- 3. firewall ----------
log "[3/5] configuring ufw"
$SUDO ufw --force default deny incoming  >/dev/null
$SUDO ufw --force default allow outgoing >/dev/null
$SUDO ufw allow OpenSSH                  >/dev/null || true
if [[ "$ROLE" == "coordinator" ]]; then
  if [[ $NO_TLS -eq 1 ]]; then
    $SUDO ufw allow 8080 >/dev/null
  else
    $SUDO ufw allow 80   >/dev/null
    $SUDO ufw allow 443  >/dev/null
  fi
fi
$SUDO ufw --force enable >/dev/null
ok "ufw active — open ports: $($SUDO ufw status | awk '/ALLOW/ {print $1}' | sort -u | paste -sd, -)"

# ---------- 4. role-specific deploy ----------
public_ip() {
  curl -fsS --max-time 4 https://api.ipify.org 2>/dev/null \
    || hostname -I 2>/dev/null | awk '{print $1}' \
    || echo "<your-server-ip>"
}

if [[ "$ROLE" == "coordinator" ]]; then
  log "[4/5] deploying coordinator"
  cd "$PROJECT_ROOT/deploy/coordinator"

  if [[ -f .env && $OVERWRITE_ENV -eq 0 ]]; then
    log "Keeping existing .env (pass --overwrite-env to regenerate)."
    # shellcheck disable=SC1091
    set -a; . ./.env; set +a
    DOMAIN="${DOMAIN:-${DOMAIN_FROM_ENV:-$DOMAIN}}"
    ADMIN_TOKEN="$COORDINATOR_ADMIN_TOKEN"
    PROBER_TOKENS="$COORDINATOR_API_TOKENS"
  else
    if [[ $NO_TLS -eq 0 ]]; then
      if [[ -z "$DOMAIN" ]]; then
        [[ $ASSUME_YES -eq 1 ]] && die "--domain required when --yes is set"
        read -rp "Domain pointing to this server (e.g. coordinator.example.com): " DOMAIN
      fi
      if [[ -z "$EMAIL" ]]; then
        [[ $ASSUME_YES -eq 1 ]] && die "--email required when --yes is set"
        read -rp "Email for Let's Encrypt: " EMAIL
      fi
    fi
    [[ -z "$ADMIN_TOKEN"   ]] && ADMIN_TOKEN="$(openssl rand -hex 32)"
    [[ -z "$PROBER_TOKENS" ]] && PROBER_TOKENS="$(openssl rand -hex 24)"

    cat > .env <<EOF
DOMAIN=$DOMAIN
ACME_EMAIL=$EMAIL
COORDINATOR_API_TOKENS=$PROBER_TOKENS
COORDINATOR_ADMIN_TOKEN=$ADMIN_TOKEN
EOF
    chmod 600 .env
    ok "Wrote $(pwd)/.env (chmod 600)"
  fi

  if [[ $NO_TLS -eq 1 ]]; then
    log "Bringing up coordinator WITHOUT TLS on :8080 (testing only)."
    cat > docker-compose.no-tls.yml <<'EOF'
services:
  coordinator:
    build:
      context: ../..
      dockerfile: coordinator/Dockerfile
    container_name: vpn-prober-coordinator
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      COORDINATOR_HOST: 0.0.0.0
      COORDINATOR_PORT: "8080"
      COORDINATOR_DB_URL: "sqlite+aiosqlite:///./data/coordinator.db"
      COORDINATOR_API_TOKENS: "${COORDINATOR_API_TOKENS}"
      COORDINATOR_ADMIN_TOKEN: "${COORDINATOR_ADMIN_TOKEN}"
    volumes:
      - coordinator-data:/app/data
volumes:
  coordinator-data:
EOF
    $COMPOSE -f docker-compose.no-tls.yml up -d --build
  else
    $COMPOSE up -d --build
  fi

  log "[5/5] health check"
  sleep 4
  if [[ $NO_TLS -eq 1 ]]; then
    HEALTH_URL="http://127.0.0.1:8080/health"
  else
    HEALTH_URL="http://127.0.0.1:80/health"
  fi
  if curl -fsS -m 8 -H "Host: ${DOMAIN:-localhost}" "$HEALTH_URL" >/dev/null 2>&1; then
    ok "Coordinator responds OK on $HEALTH_URL"
  else
    warn "Coordinator did not answer health on $HEALTH_URL yet.  Check 'docker compose logs'."
  fi

  IP="$(public_ip)"
  if [[ $NO_TLS -eq 1 ]]; then
    DASH_URL="http://$IP:8080"
  else
    DASH_URL="https://$DOMAIN"
  fi

  cat <<EOF

══════════════════════════════════════════════════════════════════
  ✓ COORDINATOR INSTALLED
══════════════════════════════════════════════════════════════════
  Public IP:           $IP
  Public URL:          $DASH_URL
  Dashboard:           $DASH_URL/dashboard?token=$ADMIN_TOKEN
  Health:              curl $DASH_URL/health

  Admin token:         $ADMIN_TOKEN
  Prober token(s):     $PROBER_TOKENS

  → Save these tokens NOW (they are also in:
     $PROJECT_ROOT/deploy/coordinator/.env).

  Next: on the PROBER VPS run:

    bash scripts/install.sh --role prober \\
        --prober-name de-1 \\
        --coordinator-url $DASH_URL \\
        --prober-token ${PROBER_TOKENS%%,*}

  Logs:    docker compose -f $PROJECT_ROOT/deploy/coordinator/docker-compose.yml logs -f
  Stop:    docker compose -f $PROJECT_ROOT/deploy/coordinator/docker-compose.yml down
══════════════════════════════════════════════════════════════════
EOF

else
  # ROLE == prober
  log "[4/5] deploying prober"
  cd "$PROJECT_ROOT/deploy/prober"

  if [[ -f .env && $OVERWRITE_ENV -eq 0 ]]; then
    log "Keeping existing .env (pass --overwrite-env to regenerate)."
    # shellcheck disable=SC1091
    set -a; . ./.env; set +a
    PROBER_NAME="${PROBER_NAME:-$PROBER_NAME}"
    COORDINATOR_URL="${COORDINATOR_URL:-$COORDINATOR_URL}"
    PROBER_TOKEN="${PROBER_TOKEN:-${PROBER_API_TOKEN:-}}"
  else
    if [[ -z "$PROBER_NAME" ]]; then
      [[ $ASSUME_YES -eq 1 ]] && die "--prober-name required when --yes is set"
      read -rp "Prober name (e.g. de-1): " PROBER_NAME
    fi
    if [[ -z "$COORDINATOR_URL" ]]; then
      [[ $ASSUME_YES -eq 1 ]] && die "--coordinator-url required when --yes is set"
      read -rp "Coordinator URL (e.g. https://coordinator.example.com): " COORDINATOR_URL
    fi
    if [[ -z "$PROBER_TOKEN" ]]; then
      [[ $ASSUME_YES -eq 1 ]] && die "--prober-token required when --yes is set"
      read -rp "Prober token (from coordinator install output): " PROBER_TOKEN
    fi
    cat > .env <<EOF
PROBER_NAME=$PROBER_NAME
COORDINATOR_URL=$COORDINATOR_URL
PROBER_API_TOKEN=$PROBER_TOKEN
EOF
    chmod 600 .env
    ok "Wrote $(pwd)/.env (chmod 600)"
  fi

  $COMPOSE up -d --build

  log "[5/5] waiting for prober to register"
  sleep 6
  if $COMPOSE logs --tail=80 prober 2>/dev/null | grep -qi "registered with"; then
    ok "Prober '$PROBER_NAME' registered with $COORDINATOR_URL"
  else
    warn "Prober did not log 'registered with' yet.  Check 'docker compose logs prober'."
  fi

  cat <<EOF

══════════════════════════════════════════════════════════════════
  ✓ PROBER INSTALLED
══════════════════════════════════════════════════════════════════
  Name:                $PROBER_NAME
  Coordinator:         $COORDINATOR_URL
  Status:              docker compose -f $PROJECT_ROOT/deploy/prober/docker-compose.yml ps
  Logs:                docker compose -f $PROJECT_ROOT/deploy/prober/docker-compose.yml logs -f
  Stop:                docker compose -f $PROJECT_ROOT/deploy/prober/docker-compose.yml down

  Open the coordinator dashboard — '$PROBER_NAME' should appear in the
  Probers list within a minute.
══════════════════════════════════════════════════════════════════
EOF
fi
