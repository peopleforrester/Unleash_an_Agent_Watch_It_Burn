# ABOUTME: Per-account change record for the fleet: AWS Config on the EKS, S3, IAM and Bedrock types, plus one
# ABOUTME: multi-region CloudTrail trail, so an out-of-band change is on record even when nothing reconciles it.
#
# Why this exists (#205). Argo CD puts the Kubernetes plane back on its own. Nothing puts the AWS plane back:
# Terraform only sees what is in a state file, and a refresh-only plan only reports drift on resources it
# already manages. A bucket somebody makes by hand is in no state, so no plan will ever mention it. Config
# is the record of what exists and how it changed, CloudTrail is the record of who did it, and
# infra/terraform/drift/drift-report.py reads both alongside the plans. docs/floor.md has the whole picture.
#
# One apply per fleet account, each into its own state, the same shape as the lab VPC:
#
#   terraform -chdir=infra/terraform/aws/audit init
#   terraform -chdir=infra/terraform/aws/audit apply -state=states/<profile>.tfstate -var profile=<profile>
#
# AWS allows ONE customer-managed configuration recorder per account and region. If the lab provider or the
# co-tenant already runs one, this apply fails on the recorder; check first with
#   aws configservice describe-configuration-recorders --profile <profile> --region us-west-2
# and if one is recording AWS::S3::Bucket and AWS::EKS::Cluster already, the drift report accepts it as is.
#
# Cost, for a lab account: Config bills per configuration item recorded (continuous recording of these few
# types is cents a day), and the first copy of management events in a trail is free. Teardown is
# `terraform destroy` with the same -state; the bucket has force_destroy because the record is disposable
# with the account's lab.

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
  region  = var.region
  profile = var.profile
  # Same collision rule as the lab VPC: accen-dev is shared with the Packt project, so everything here is
  # tagged ours and is found by tag, never by guessing.
  default_tags {
    tags = {
      project   = "watch-it-burn"
      Purpose   = "fleet-audit"
      ManagedBy = "terraform"
    }
  }
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "profile" {
  type = string
  # NO DEFAULT, for the reason the lab VPC root gives: an implicit profile points a second account's apply
  # at the first account and writes the result into the second account's state.
  description = "AWS profile of the fleet account this records. Required; every caller passes it explicitly."
}

# What Config records. EKS and S3 are the planes the fleet builds on; IAM is where the attendee keys live
# (users made by generate_attendee_aws.py, outside Terraform); Bedrock is the model the agent calls; the
# trail itself is recorded so turning it off is on record too. The EKS list is every AWS::EKS:: type in the
# Config resource reference as read on 2026-10-24 (there is no access-entry type). IAM types are global and
# are recorded by this one regional recorder; record them in one region only.
variable "recorded_resource_types" {
  type = list(string)
  default = [
    "AWS::EKS::Cluster",
    "AWS::EKS::Nodegroup",
    "AWS::EKS::Addon",
    "AWS::EKS::FargateProfile",
    "AWS::EKS::IdentityProviderConfig",
    "AWS::EKS::PodIdentityAssociation",
    "AWS::S3::Bucket",
    "AWS::S3::BucketPolicy",
    "AWS::S3::AccountPublicAccessBlock",
    "AWS::IAM::User",
    "AWS::IAM::Role",
    "AWS::IAM::Policy",
    "AWS::Bedrock::ApplicationInferenceProfile",
    "AWS::Bedrock::Guardrail",
    "AWS::CloudTrail::Trail",
  ]
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  name       = "watch-it-burn"
  bucket     = "watch-it-burn-audit-${local.account_id}-${var.region}"
  # Built rather than read from the trail, because the bucket policy has to exist before the trail does.
  trail_arn = "arn:${local.partition}:cloudtrail:${var.region}:${local.account_id}:trail/${local.name}"
}

resource "aws_s3_bucket" "audit" {
  bucket        = local.bucket
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# The record outlives any one event by a few months at most; it is evidence for this lab, not an archive.
resource "aws_s3_bucket_lifecycle_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
  }
}

data "aws_iam_policy_document" "audit_bucket" {
  statement {
    sid       = "ConfigAndTrailReadAcl"
    actions   = ["s3:GetBucketAcl", "s3:ListBucket"]
    resources = [aws_s3_bucket.audit.arn]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com", "cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
  statement {
    sid       = "ConfigWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/config/AWSLogs/${local.account_id}/Config/*"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
  statement {
    sid       = "TrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/cloudtrail/AWSLogs/${local.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.audit.arn,
      "${aws_s3_bucket.audit.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = data.aws_iam_policy_document.audit_bucket.json
  # The public access block has to be in place first or S3 can reject the policy write.
  depends_on = [aws_s3_bucket_public_access_block.audit]
}

data "aws_iam_policy_document" "config_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

# A role of our own rather than the service-linked role: the service-linked role is one per account, and in a
# co-tenant account it may already belong to somebody else's recorder.
resource "aws_iam_role" "config" {
  name               = "${local.name}-config-recorder"
  assume_role_policy = data.aws_iam_policy_document.config_assume.json
}

resource "aws_iam_role_policy_attachment" "config" {
  role       = aws_iam_role.config.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "fleet" {
  name     = local.name
  role_arn = aws_iam_role.config.arn
  recording_group {
    all_supported  = false
    resource_types = var.recorded_resource_types
    recording_strategy {
      use_only = "INCLUSION_BY_RESOURCE_TYPES"
    }
  }
  recording_mode {
    recording_frequency = "CONTINUOUS"
  }
}

resource "aws_config_delivery_channel" "fleet" {
  name           = local.name
  s3_bucket_name = aws_s3_bucket.audit.id
  s3_key_prefix  = "config"
  snapshot_delivery_properties {
    delivery_frequency = "TwentyFour_Hours"
  }
  depends_on = [aws_config_configuration_recorder.fleet, aws_s3_bucket_policy.audit]
}

resource "aws_config_configuration_recorder_status" "fleet" {
  name       = aws_config_configuration_recorder.fleet.name
  is_enabled = true
  depends_on = [aws_config_delivery_channel.fleet]
}

# Management events in every region: an out-of-band CreateBucket is a management event wherever it lands.
# Event history already keeps 90 days of these without a trail; the trail is what keeps them past that and
# what proves (log file validation) that nobody edited them.
resource "aws_cloudtrail" "fleet" {
  name                          = local.name
  s3_bucket_name                = aws_s3_bucket.audit.id
  s3_key_prefix                 = "cloudtrail"
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  depends_on                    = [aws_s3_bucket_policy.audit]
}

output "config_recorder" {
  value = aws_config_configuration_recorder.fleet.name
}

output "trail_arn" {
  value = aws_cloudtrail.fleet.arn
}

output "audit_bucket" {
  value = aws_s3_bucket.audit.id
}
