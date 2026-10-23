output "instance_id" {
  value = aws_instance.box.id
}

output "public_ip" {
  value = aws_eip.box.public_ip
}

output "url" {
  value = "https://${local.fqdn}"
}

output "backup_bucket" {
  value = aws_s3_bucket.backup.bucket
}

output "ssm_shell" {
  value = "aws ssm start-session --target ${aws_instance.box.id}"
}

output "evidence_bucket" {
  value = aws_s3_bucket.evidence.bucket
}
