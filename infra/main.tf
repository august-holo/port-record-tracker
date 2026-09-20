terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name = "terminal-state-archive"
  fqdn = "${var.subdomain}.${var.zone_name}"
}

# ── Existing DNS zone ─────────────────────────────────────────────────
data "aws_route53_zone" "main" {
  name = var.zone_name
}

# ── AMI: Amazon Linux 2023, arm64 ────────────────────────────────────
data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023*-arm64"]
  }
  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

data "aws_vpc" "default" {
  default = true
}

# ── Backup bucket: Litestream db replica + raw body sync ─────────────
resource "aws_s3_bucket" "backup" {
  bucket_prefix = "${local.name}-backup-"
}

resource "aws_s3_bucket_versioning" "backup" {
  bucket = aws_s3_bucket.backup.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Instance role: SSM shell + backup bucket only ────────────────────
resource "aws_iam_role" "instance" {
  name = "${local.name}-instance"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "backup_bucket" {
  name = "backup-bucket"
  role = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.backup.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.backup.arn}/*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name}-instance"
  role = aws_iam_role.instance.name
}

# ── Security group: TLS + ACME only; shell is SSM, not SSH ───────────
resource "aws_security_group" "web" {
  name        = "${local.name}-web"
  description = "HTTP(S) in; everything out"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "ACME HTTP-01 + redirect to https"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "TLS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── The box ──────────────────────────────────────────────────────────
resource "aws_instance" "box" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.instance.name
  vpc_security_group_ids = [aws_security_group.web.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = var.volume_gb
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    contact_email = var.contact_email
    backup_bucket = aws_s3_bucket.backup.bucket
    fqdn          = local.fqdn
  })

  tags = { Name = local.name }
}

resource "aws_eip" "box" {
  instance = aws_instance.box.id
  tags     = { Name = local.name }
}

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.fqdn
  type    = "A"
  ttl     = 300
  records = [aws_eip.box.public_ip]
}
