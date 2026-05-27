terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

locals {
  app_name = "app18"
  common_tags = {
    Application = local.app_name
    ManagedBy   = "data-gen-pipeline"
  }
}

resource "aws_launch_template" "compute" {
  name_prefix   = "${local.app_name}-compute-"
  image_id      = "ami-0c55b159cbfafe1f0"   # placeholder Amazon Linux 2
  instance_type = "t3.medium"

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, { Tier = "compute" })
  }
}

resource "aws_instance" "compute" {
  count                  = 5
  launch_template {
    id      = aws_launch_template.compute.id
    version = "$Latest"
  }
  tags = merge(local.common_tags, { Tier = "compute" })
}

resource "aws_db_instance" "database_primary" {
  identifier              = "${local.app_name}-db-primary"
  engine                  = "postgres"
  engine_version          = "16.1"
  instance_class          = "db.r6g.large"
  allocated_storage       = 200
  storage_encrypted       = true
  skip_final_snapshot     = true
  username                = "appuser"
  password                = "placeholder-rotate-in-prod"
  publicly_accessible     = false

  tags = merge(local.common_tags, { Tier = "database", Role = "primary" })
}



resource "aws_lb" "main" {
  name               = "${local.app_name}-lb"
  internal           = false
  load_balancer_type = "application"
  subnets            = ["subnet-placeholder-a", "subnet-placeholder-b"]

  tags = merge(local.common_tags, { Tier = "network" })
}

resource "aws_lb_target_group" "main" {
  name     = "${local.app_name}-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = "vpc-placeholder"

  load_balancing_algorithm_type = "least_outstanding_requests"

  tags = merge(local.common_tags, { Tier = "network" })
}

resource "aws_lb_listener" "main" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.main.arn
  }
}

resource "aws_security_group_rule" "compute_to_database" {
  description       = "app18: compute tier queries database tier"
  type              = "ingress"
  from_port         = 5432
  to_port           = 5432
  protocol          = "tcp"
  security_group_id = "sg-placeholder-database"
  source_security_group_id = "sg-placeholder-compute"
}
