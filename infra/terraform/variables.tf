variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_suffix" {
  type    = string
  default = "demo"
}

variable "instance_type" {
  type    = string
  default = "t3.xlarge" # 4 vCPU / 16 GB
}

variable "disk_gb" {
  type    = number
  default = 100
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  type        = string
  description = "Tu IP pública en formato a.b.c.d/32 para el SSH"
}

variable "repo_url" {
  type        = string
  description = "URL https del repo de GitHub (público, o con token embebido)"
}

variable "repo_branch" {
  type    = string
  default = "main"
}

variable "mongo_user" {
  type    = string
  default = "admin"
}

variable "mongo_password" {
  type      = string
  sensitive = true
}

variable "ngrok_authtoken" {
  type      = string
  default   = ""
  sensitive = true
}

variable "ngrok_domain" {
  type    = string
  default = ""
}

variable "vpc_name" {
  type    = string
  default = "vpc-iue-vpc"
}

variable "subnet_name" {
  type    = string
  default = "vpc-iue-subnet-public1-us-east-1a"
}

variable "s3_bucket" {
  type    = string
  default = "iue-bucket-ecs-893"
}
