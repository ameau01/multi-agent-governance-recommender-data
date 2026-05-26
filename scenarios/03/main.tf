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
  app_name = "app03"
  common_tags = {
    Application = local.app_name
    ManagedBy   = "data-gen-pipeline"
  }
}


resource "aws_db_instance" "database_primary" {
  identifier              = "${local.app_name}-db-primary"
  engine                  = "postgres"
  engine_version          = "16.1"
  instance_class          = "db.r6g.xlarge"
  allocated_storage       = 200
  storage_encrypted       = true
  skip_final_snapshot     = true
  username                = "appuser"
  password                = "placeholder-rotate-in-prod"
  publicly_accessible     = false

  tags = merge(local.common_tags, { Tier = "database", Role = "primary" })
}





