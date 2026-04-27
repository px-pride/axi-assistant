#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${INSTALL_DIR:-$HOME/.local/bin}"
proxy_git="${ANTHROPIC_PROXY_RS_GIT:-https://github.com/m0n0x41d/anthropic-proxy-rs}"
proxy_rev="${ANTHROPIC_PROXY_RS_REV:-bc6cbdf2f7bf1ab00c9894969b47c9344c30d3b0}"
install_proxy=1
force_proxy=0
install_systemd=0
start_service=0

usage() {
  cat <<'EOF'
usage: scripts/anthropic-codex-proxy/install.sh [options]

Options:
  --skip-rust-proxy   Do not run cargo install for anthropic-proxy-rs.
  --force-rust-proxy  Reinstall pinned anthropic-proxy-rs even if it exists.
  --systemd           Install a user systemd service named anthropic-proxy-codex.service.
  --start             Start the installed proxy after installing files.
  -h, --help          Show this help.

Environment:
  INSTALL_DIR                 Directory for wrapper scripts (default: $HOME/.local/bin)
  ANTHROPIC_PROXY_RS_GIT      Git URL for anthropic-proxy-rs
  ANTHROPIC_PROXY_RS_REV      Git revision to install
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-rust-proxy)
      install_proxy=0
      shift
      ;;
    --force-rust-proxy)
      force_proxy=1
      shift
      ;;
    --systemd)
      install_systemd=1
      shift
      ;;
    --start)
      start_service=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for cmd in python3 curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing required command: $cmd" >&2
    exit 1
  fi
done

mkdir -p "$install_dir"

for script in \
  codex-chatgpt-openai-shim \
  anthropic-request-normalizer \
  anthropic-proxy-codex \
  anthropic-proxy-codex-service \
  claude-gpt54
do
  install -m 0755 "$script_dir/$script" "$install_dir/$script"
done

# _proxy_auth.py is a Python module imported by the normalizer and shim, not
# a runnable script — install it 0644 alongside the executables.
install -m 0644 "$script_dir/_proxy_auth.py" "$install_dir/_proxy_auth.py"

if [[ "$install_proxy" == "1" ]]; then
  if [[ "$force_proxy" == "1" ]] || ! command -v anthropic-proxy >/dev/null 2>&1; then
    if ! command -v cargo >/dev/null 2>&1; then
      echo "cargo is required to install anthropic-proxy-rs; install Rust or rerun with --skip-rust-proxy" >&2
      exit 1
    fi
    cargo install --git "$proxy_git" --rev "$proxy_rev" --locked --force
  else
    echo "anthropic-proxy already exists at $(command -v anthropic-proxy)"
  fi
fi

if [[ "$install_systemd" == "1" ]]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl is required for --systemd" >&2
    exit 1
  fi
  unit_dir="$HOME/.config/systemd/user"
  mkdir -p "$unit_dir"
  cat >"$unit_dir/anthropic-proxy-codex.service" <<EOF
[Unit]
Description=Anthropic-compatible ChatGPT/Codex proxy for Axi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=HOME=%h
Environment=PATH=%h/.local/bin:%h/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=PORT=3000
ExecStart=$install_dir/anthropic-proxy-codex
Restart=always
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  echo "installed user service: anthropic-proxy-codex.service"
fi

if [[ "$start_service" == "1" ]]; then
  if [[ "$install_systemd" == "1" ]]; then
    systemctl --user enable --now anthropic-proxy-codex.service
    systemctl --user status --no-pager anthropic-proxy-codex.service || true
  else
    "$install_dir/anthropic-proxy-codex-service" start
  fi
fi

cat <<EOF
Installed ChatGPT/Codex Anthropic proxy helpers to $install_dir

Next steps:
  1. Log in with Codex CLI or set OPENAI_API_KEY in ~/.codex/auth.json.
  2. Start the proxy:
       $install_dir/anthropic-proxy-codex-service start
  3. Set Axi .env:
       AXI_HARNESS=claude_code
       AXI_MODEL=gpt-5.4
EOF
