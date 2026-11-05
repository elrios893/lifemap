terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# Ubuntu 24.04 LTS (parámetro público de SSM, siempre la AMI vigente)
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

# Se reutiliza la VPC existente de la cuenta (nombre configurable) y su subred pública.
data "aws_vpc" "main" {
  tags = { Name = var.vpc_name }
}

data "aws_subnet" "public" {
  vpc_id = data.aws_vpc.main.id
  tags   = { Name = var.subnet_name }
}

resource "aws_key_pair" "lifemap" {
  key_name   = "lifemap-${var.name_suffix}"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_security_group" "lifemap" {
  name_prefix = "lifemap-"
  description = "LifeMap: SSH, API y Jenkins"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description = "SSH (solo tu IP)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }
  ingress {
    description = "API Flask"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "Jenkins UI + webhook de GitHub"
    from_port   = 8088
    to_port     = 8088
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

# Rol de instancia: la VM lee/escribe solo bajo s3://<bucket>/lifemap/ (sin llaves guardadas en la VM).
resource "aws_iam_role" "vm" {
  name = "lifemap-vm-${var.name_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "vm_s3" {
  name = "s3-lifemap"
  role = aws_iam_role.vm.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = "arn:aws:s3:::${var.s3_bucket}"
        Condition = { StringLike = { "s3:prefix" = ["lifemap/*"] } }
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "arn:aws:s3:::${var.s3_bucket}/lifemap/*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "vm" {
  name = "lifemap-vm-${var.name_suffix}"
  role = aws_iam_role.vm.name
}

resource "aws_instance" "lifemap" {
  ami                    = nonsensitive(data.aws_ssm_parameter.ubuntu.value)
  instance_type          = var.instance_type
  key_name               = aws_key_pair.lifemap.key_name
  iam_instance_profile   = aws_iam_instance_profile.vm.name
  subnet_id              = data.aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.lifemap.id]

  root_block_device {
    volume_size = var.disk_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url       = var.repo_url
    repo_branch    = var.repo_branch
    mongo_user     = var.mongo_user
    mongo_password = var.mongo_password
    ngrok_token    = var.ngrok_authtoken
    ngrok_domain   = var.ngrok_domain
    s3_bucket      = var.s3_bucket
    jenkins_pw     = var.jenkins_admin_password
  })
  user_data_replace_on_change = true

  tags = { Name = "lifemap" }
}

resource "aws_eip" "lifemap" {
  instance = aws_instance.lifemap.id
  domain   = "vpc"
}
