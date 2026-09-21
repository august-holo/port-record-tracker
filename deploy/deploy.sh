#!/usr/bin/env bash
# Ship the working tree to the box and (re)start the stack — no SSH, no git remote.
# Path: tar → S3 backup bucket → SSM command on the instance pulls + untars + rebuilds.
# Images are built while the old containers keep running, and only changed containers are
# swapped, so capturing pauses for seconds, not for the length of a build. data/ and .env on
# the box are never in the tarball, so a deploy cannot touch the archive.
#
# Usage: deploy/deploy.sh            (reads instance id + bucket from terraform output)
set -euo pipefail
cd "$(dirname "$0")/.."

INSTANCE_ID=$(terraform -chdir=infra output -raw instance_id)
BUCKET=$(terraform -chdir=infra output -raw backup_bucket)
REV=$(git rev-parse --short HEAD)
git diff --quiet HEAD -- || REV="$REV-dirty"
KEY="deploys/tsa-$(date -u +%Y%m%dT%H%M%SZ)-$REV.tar.gz"

echo "→ packing working tree at $REV"
echo "$REV $(date -u +%Y-%m-%dT%H:%M:%SZ)" > REVISION # lands in /opt/tsa: which code is running
trap 'rm -f REVISION /tmp/tsa-deploy.tar.gz' EXIT
COPYFILE_DISABLE=1 tar --no-xattrs --exclude .git --exclude .terraform --exclude '*.tfstate*' --exclude .env --exclude .venv --exclude data --exclude node_modules \
    --exclude .next --exclude __pycache__ \
    -czf /tmp/tsa-deploy.tar.gz .

echo "→ uploading to s3://$BUCKET/$KEY"
aws s3 cp /tmp/tsa-deploy.tar.gz "s3://$BUCKET/$KEY" --no-progress

echo "→ deploying on $INSTANCE_ID"
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "tsa deploy $KEY" \
  --parameters "commands=[
    'set -e',
    'aws s3 cp s3://$BUCKET/$KEY /tmp/tsa-deploy.tar.gz --no-progress',
    'mkdir -p /opt/tsa && tar -xzf /tmp/tsa-deploy.tar.gz -C /opt/tsa',
    'cd /opt/tsa',
    'docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml build',
    'docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --remove-orphans'
  ]" \
  --query Command.CommandId --output text)

aws ssm wait command-executed --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" || true
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
