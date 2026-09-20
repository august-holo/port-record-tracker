#!/bin/bash
# Cloud-init for the terminal-state-archive box (Amazon Linux 2023, arm64).
# Installs docker + compose, prepares /opt/tsa, and a systemd unit that brings
# the stack up on boot. App code arrives via deploy/deploy.sh (tarball through S3 + SSM).
set -euxo pipefail

# Swap, so an image build cannot take the box down by exhausting memory.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon -a

dnf install -y docker
systemctl enable --now docker

# docker compose plugin (not packaged in AL2023)
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/v5.5.1/docker-compose-linux-aarch64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

mkdir -p /opt/tsa/data
cat > /opt/tsa/.env <<EOF
CONTACT_EMAIL=${contact_email}
BACKUP_BUCKET=${backup_bucket}
EVIDENCE_BUCKET=${evidence_bucket}
AWS_REGION=${aws_region}
FQDN=${fqdn}
HEALTHCHECK_PING_URL=${healthcheck_ping_url}
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
# Not started here: the unit starts on next boot or after the first deploy/deploy.sh.
