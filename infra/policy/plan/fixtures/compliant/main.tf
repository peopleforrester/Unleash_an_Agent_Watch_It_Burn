# ABOUTME: Test root with the compliant twin of every violation in ../violating, which no policy may reject.
# ABOUTME: Plans without AWS credentials (no data sources, skip_* flags); it is never applied.
#
# This is the false-positive half of the proof. A policy that rejects everything passes the violating
# fixture too, so each one also has to let the safe version of the same resource through.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region                      = "us-west-2"
  access_key                  = "fixture-not-a-real-key"
  secret_key                  = "fixture-not-a-real-key"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

resource "aws_s3_bucket" "private" {
  bucket = "watch-it-burn-fixture-private"
}

resource "aws_s3_bucket_acl" "private" {
  bucket = aws_s3_bucket.private.id
  acl    = "private"
}

resource "aws_eks_cluster" "private_endpoint" {
  name     = "watch-it-burn-fixture-private-endpoint"
  role_arn = "arn:aws:iam::123456789012:role/watch-it-burn-fixture"

  vpc_config {
    subnet_ids              = ["subnet-0fixture000000001", "subnet-0fixture000000002"]
    endpoint_public_access  = false
    endpoint_private_access = true
  }
}

# A wildcard inside an ARN is not the bare "*" the policy forbids: it is scoped to one bucket.
resource "aws_iam_policy" "scoped" {
  name = "watch-it-burn-fixture-scoped"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::watch-it-burn-fixture-private/*"]
    }]
  })
}

# Deny statements are not grants, so a Deny on "*" is the opposite of what the policy is guarding against.
resource "aws_iam_role_policy" "deny_all_deletes" {
  name = "watch-it-burn-fixture-deny-deletes"
  role = "watch-it-burn-fixture"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Deny", Action = "s3:DeleteBucket", Resource = "*" }]
  })
}

resource "aws_db_instance" "encrypted" {
  identifier          = "watch-it-burn-fixture-encrypted"
  engine              = "postgres"
  instance_class      = "db.t4g.micro"
  allocated_storage   = 20
  username            = "fixture"
  password            = "fixture-not-a-password"
  storage_encrypted   = true
  skip_final_snapshot = true
}

resource "aws_rds_cluster" "encrypted" {
  cluster_identifier  = "watch-it-burn-fixture-encrypted"
  engine              = "aurora-postgresql"
  master_username     = "fixture"
  master_password     = "fixture-not-a-password"
  storage_encrypted   = true
  skip_final_snapshot = true
}
