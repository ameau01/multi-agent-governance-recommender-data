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
  app_name = "app05"
  common_tags = {
    Application = local.app_name
    ManagedBy   = "data-gen-pipeline"
  }
}

resource "aws_launch_template" "compute" {
  name_prefix   = "${local.app_name}-compute-"
  image_id      = "ami-0c55b159cbfafe1f0"   # placeholder Amazon Linux 2
  instance_type = "c5.xlarge"

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, { Tier = "compute" })
  }
}

resource "aws_instance" "compute" {
  count                  = 8
  launch_template {
    id      = aws_launch_template.compute.id
    version = "$Latest"
  }
  tags = merge(local.common_tags, { Tier = "compute" })
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

  load_balancing_algorithm_type = "round_robin"

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


