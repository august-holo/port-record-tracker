variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "zone_name" {
  description = "Existing Route 53 hosted zone"
  type        = string
  default     = "holotekt.com"
}

variable "subdomain" {
  description = "Host label under the zone"
  type        = string
  default     = "port-record-lookup"
}

variable "instance_type" {
  type    = string
  default = "t4g.small" # arm64. 2 GB: a t4g.micro (1 GB) runs out of memory building the Next.js image
}

variable "volume_gb" {
  type    = number
  default = 10
}

variable "contact_email" {
  description = "Goes into the scraper User-Agent (CONTACT_EMAIL)"
  type        = string
}

variable "healthcheck_ping_url" {
  description = "healthchecks.io-style check URL pinged hourly by the scheduler; empty disables it"
  type        = string
  default     = ""
}

variable "evidence_retention_days" {
  description = "Object Lock (governance) retention on raw bodies and capture manifests"
  type        = number
  default     = 365
}
