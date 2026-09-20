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
  default = "t4g.micro" # arm64; images must be built for linux/arm64
}

variable "volume_gb" {
  type    = number
  default = 10
}

variable "contact_email" {
  description = "Goes into the scraper User-Agent (CONTACT_EMAIL)"
  type        = string
}
