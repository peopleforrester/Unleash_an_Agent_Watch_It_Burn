# ABOUTME: Test root that breaks every plan-time policy once, so each policy is proven to fire by name.
# ABOUTME: Plans without AWS credentials (no data sources, skip_* flags); it is never applied.
#
# Every resource here is a single, deliberate violation, and the e2e test asserts the exact policy that
# names it. The comment on each says which. A resource that trips no policy does not belong here; one that
# trips two makes a failure ambiguous.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Fake keys and every skip_* flag: planning resources that do not exist yet makes no AWS call, so the
# fixture plans on a machine with no AWS access at all. That is what lets the e2e suite run it anywhere.
provider "aws" {
  region                      = "us-west-2"
  access_key                  = "fixture-not-a-real-key"
  secret_key                  = "fixture-not-a-real-key"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

# no-public-s3-acl: the acceptance case from #200, a canned public ACL on the bucket itself.
resource "aws_s3_bucket" "public_read" {
  bucket = "watch-it-burn-fixture-public-read"
  acl    = "public-read"
}

# no-public-s3-acl: the same grant through the separate ACL resource, which is how the provider has
# preferred it since v4. Checking only aws_s3_bucket.acl would miss it.
resource "aws_s3_bucket" "acl_elsewhere" {
  bucket = "watch-it-burn-fixture-acl-elsewhere"
}

resource "aws_s3_bucket_acl" "public_read_write" {
  bucket = aws_s3_bucket.acl_elsewhere.id
  acl    = "public-read-write"
}

# no-public-s3-acl: no canned ACL at all, just an explicit READ grant to the AllUsers group.
resource "aws_s3_bucket" "grant_elsewhere" {
  bucket = "watch-it-burn-fixture-grant-elsewhere"
}

resource "aws_s3_bucket_acl" "all_users_grant" {
  bucket = aws_s3_bucket.grant_elsewhere.id

  access_control_policy {
    owner {
      id = "fixture-owner-canonical-id"
    }
    grant {
      permission = "READ"
      grantee {
        type = "Group"
        uri  = "http://acs.amazonaws.com/groups/global/AllUsers"
      }
    }
  }
}

# no-public-eks-endpoint: endpoint_public_access is left at its default, which is true. A policy that only
# caught an explicit `= true` would pass this.
resource "aws_eks_cluster" "default_endpoint" {
  name     = "watch-it-burn-fixture-default-endpoint"
  role_arn = "arn:aws:iam::123456789012:role/watch-it-burn-fixture"

  vpc_config {
    subnet_ids = ["subnet-0fixture000000001", "subnet-0fixture000000002"]
  }
}

# no-iam-wildcard: full admin, Action and Resource both "*".
resource "aws_iam_policy" "admin" {
  name = "watch-it-burn-fixture-admin"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "*", Resource = "*" }]
  })
}

# no-iam-wildcard: a scoped action on every resource, in an inline role policy rather than a managed one.
resource "aws_iam_role_policy" "any_bucket" {
  name = "watch-it-burn-fixture-any-bucket"
  role = "watch-it-burn-fixture"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["s3:GetObject"], Resource = ["*"] }]
  })
}

# no-iam-wildcard: NotAction in an Allow grants every action except the listed one. Inline on the role,
# which is a different place in the plan from a policy resource.
resource "aws_iam_role" "not_action" {
  name = "watch-it-burn-fixture-not-action"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })

  inline_policy {
    name = "everything-but-iam"
    policy = jsonencode({
      Version   = "2012-10-17"
      Statement = [{ Effect = "Allow", NotAction = ["iam:*"], Resource = ["arn:aws:s3:::watch-it-burn-fixture/*"] }]
    })
  }
}

# no-iam-wildcard: "*:*", with Statement as a single object instead of a list (both are valid IAM).
resource "aws_iam_user_policy" "star_colon_star" {
  name = "watch-it-burn-fixture-star-colon-star"
  user = "watch-it-burn-fixture"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = { Effect = "Allow", Action = "*:*", Resource = "arn:aws:s3:::watch-it-burn-fixture" }
  })
}

# no-unencrypted-rds: storage_encrypted left at its default, which is false.
resource "aws_db_instance" "plain" {
  identifier          = "watch-it-burn-fixture-plain"
  engine              = "postgres"
  instance_class      = "db.t4g.micro"
  allocated_storage   = 20
  username            = "fixture"
  password            = "fixture-not-a-password"
  skip_final_snapshot = true
}

# no-unencrypted-rds: an Aurora cluster with encryption explicitly off.
resource "aws_rds_cluster" "plain" {
  cluster_identifier  = "watch-it-burn-fixture-plain"
  engine              = "aurora-postgresql"
  master_username     = "fixture"
  master_password     = "fixture-not-a-password"
  storage_encrypted   = false
  skip_final_snapshot = true
}
