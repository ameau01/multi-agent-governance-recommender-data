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
  app_name = "app10"
  common_tags = {
    Application = local.app_name
    ManagedBy   = "data-gen-pipeline"
  }
}

resource "aws_launch_template" "compute" {
  name_prefix   = "${local.app_name}-compute-"
  image_id      = "ami-0c55b159cbfafe1f0"
  instance_type = "m5.large"

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, { Tier = "compute" })
  }
}

resource "aws_autoscaling_group" "compute" {
  name                = "${local.app_name}-compute-asg"
  min_size            = 6
  max_size            = 10
  desired_capacity    = 6
  vpc_zone_identifier = ["subnet-placeholder-a", "subnet-placeholder-b"]

  launch_template {
    id      = aws_launch_template.compute.id
    version = "$Latest"
  }

  tag {
    key                 = "Application"
    value               = local.app_name
    propagate_at_launch = true
  }
  tag {
    key                 = "Tier"
    value               = "compute"
    propagate_at_launch = true
  }
}



resource "aws_lb" "main" {
  name               = "${local.app_name}-lb"
  internal           = false
  load_balancer_type = "network"
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


