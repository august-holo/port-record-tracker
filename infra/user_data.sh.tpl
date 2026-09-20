#!/bin/bash
# Cloud-init for the terminal-state-archive box (Amazon Linux 2023, arm64).
# Installs docker + compose, prepares /opt/tsa, and a systemd unit that brings
# the stack up on boot. App code arrives via `make deploy` (rsync over SSM).
set -euxo pipefail

dnf install -y docker git rsync
systemctl enable --now docker

# docker compose plugin (not packaged in AL2023)
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

mkdir -p /opt/tsa/data
cat > /opt/tsa/.env <<EOF
CONTACT_EMAIL=${contact_email}
BACKUP_BUCKET=${backup_bucket}
FQDN=${fqdn}
EOF

cat > /etc/systemd/system/tsa.service <<'EOF'
[Unit]
Description=terminal-state-archive stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/tsa
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml down

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable tsa.service
# Not started here: the unit starts on next boot or after the first `make deploy`.
