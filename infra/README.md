# Infra: one arm64 box behind Route 53

~$19/mo: t4g.small (~$12) + 40GB gp3 (~$3) + EIP-on-running-instance/IPv4 (~$3.6) + S3 (pennies,
growing ~2 GB a month with the gate camera stills).

- EC2 t4g.small (Amazon Linux 2023, arm64, 2 GB swap) — everything runs here via docker compose
- Caddy terminates TLS for `port-record-lookup.holotekt.com` (Let's Encrypt, ports 80/443 only)
- No SSH: shell via SSM (`terraform output ssm_shell`); IMDSv2 enforced, hop limit 2 so the
  containers can reach the instance role
- S3 backup bucket (versioned, private): Litestream streams `archive.db` (10s lag); deploy tarballs
- S3 evidence bucket (versioned, private, **Object Lock**, governance mode, 365 days): hourly sync
  of the raw bodies and the daily capture manifests (`src/manifest.py`). The box can write and
  read there but not delete, so S3's own timestamps back up the archive's.
- Instance role: SSM core + those two buckets. No credentials on disk anywhere.
- Alerts: pass `-var healthcheck_ping_url=https://hc-ping.com/<uuid>` (healthchecks.io, free).
  The scheduler pings hourly; you get an email when a check fails or the pings stop.

## Deploy

```bash
cd infra
terraform init
terraform apply -var contact_email=you@example.com -var healthcheck_ping_url=https://hc-ping.com/<uuid>
cd ..
deploy/deploy.sh        # tar working tree → S3 → SSM pull + restart on the box
```

The box builds arm64 images natively. `deploy.sh` stamps the tarball and `/opt/tsa/REVISION`
with the git commit (`-dirty` if there are uncommitted changes), and leaves out `.env`, so the
box keeps the `.env` that Terraform wrote.

After the first deploy, check the backups really arrive (give it an hour for the raw sync):

```bash
aws s3 ls s3://$(terraform -chdir=infra output -raw backup_bucket)/litestream/ --recursive | head
aws s3 ls s3://$(terraform -chdir=infra output -raw evidence_bucket)/ --recursive | head
```

## Recovery (the instance is disposable)

1. `terraform apply` a fresh box (or reuse), `deploy/deploy.sh`
2. Restore db: `litestream restore -o data/archive.db s3://<bucket>/litestream/archive.db`
3. Restore raw bodies: `aws s3 sync s3://<evidence-bucket>/raw data/raw`
4. `systemctl start tsa.service`

## Tearing it down

`terraform destroy` stops at the two buckets while they hold objects. That is deliberate for
the evidence bucket: its objects are locked, and removing them needs
`s3:BypassGovernanceRetention` from an admin identity.

## Public surface

Caddy exposes only the exhibit UI (`/`), `/api/*`, and `/raw/*`. The capture
dashboard stays private: `aws ssm start-session --target <id> --document-name \
AWS-StartPortForwardingSession --parameters portNumber=8100,localPortNumber=8100`.
