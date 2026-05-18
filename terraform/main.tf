terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # S3バックエンド（推奨: tfstateを暗号化保存）
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "7dtd/terraform.tfstate"
  #   region         = "ap-northeast-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-state-lock"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "7dtd-server"
      ManagedBy = "terraform"
    }
  }
}
