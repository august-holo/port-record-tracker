# Infra: one arm64 box behind Route 53

~$11/mo: t4g.micro (~$6) + 10GB gp3 (~$1) + EIP-on-running-instance/IPv4 (~$3.6) + S3 (pennies).

- EC2 t4g.micro (Amazon Linux 2023, arm64) — everything runs here via docker compose
- Caddy terminates TLS for `port-record-lookup.holotekt.com` (Let's Encrypt, ports 80/443 only)
- No SSH: shell via SSM (`terraform output ssm_shell`); IMDSv2 enforced
- S3 backup bucket (versioned, private): Litestream streams `archive.db` (10s lag);
  hourly `s3 sync` of the immutable raw bodies; deploy tarballs
- Instance role: SSM core + that one bucket. No credentials on disk anywhere.

## Deploy

```bash
cd infra
terraform init
terraform apply -var contact_email=you@example.com
cd ..
deploy/deploy.sh        # tar working tree → S3 → SSM pull + restart on the box
```

First deploy note: the box builds arm64 images natively, so nothing special is
needed for architecture — but the t4g.micro's 1GB RAM makes the first
`docker compose build` (Next.js) slow. If it OOMs, build once with a swapfile:
`sudo fallocate -l 2G /swap && sudo chmod 600 /swap && sudo mkswap /swap && sudo swapon /swap`.

## Recovery (the instance is disposable)

1. `terraform apply` a fresh box (or reuse), `deploy/deploy.sh`
2. Restore db: `litestream restore -o data/archive.db s3://<bucket>/litestream/archive.db`
3. Restore raw bodies: `aws s3 sync s3://<bucket>/raw data/raw`
4. `systemctl start tsa.service`

## Public surface

Caddy exposes only the exhibit UI (`/`), `/api/*`, and `/raw/*`. The capture
dashboard stays private: `aws ssm start-session --target <id> --document-name \
AWS-StartPortForwardingSession --parameters portNumber=8100,localPortNumber=8100`.
