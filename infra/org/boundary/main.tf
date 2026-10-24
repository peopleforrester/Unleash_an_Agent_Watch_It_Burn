# ABOUTME: The canonical permissions boundary, one per AWS account, applied once before any cluster.
# ABOUTME: Every IAM role the cluster root creates carries it; the document is ../permissions-boundary.json.tftpl.
#
# Why per account and not per cluster: a role names its boundary by ARN, and a boundary created in the same
# apply as the role is either "known after apply" at plan time (so the policy pipeline cannot check it) or
# raced by CreateRole. One policy per account, applied first, is known at every cluster plan. The cluster
# root looks it up by name, so a cluster plan in an account where this was never applied fails at plan
# with "no matching IAM Policy found" rather than creating unbounded roles.
#
# Apply, per account, with that account's own state file (the same layout as ../../terraform/aws/network):
#   terraform -chdir=infra/org/boundary init
#   terraform -chdir=infra/org/boundary apply -state=states/<profile>.tfstate -var profile=<profile>
#
# The document is the boundary's whole content and lives in the template, not here, so the pipeline's
# offline checks and its effect tests read the same text this applies.

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
  default_tags {
    tags = {
      project   = "watch-it-burn"
      event     = "devopsdays-portland-2026"
      Purpose   = "permissions-boundary"
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
  # No default, for the reason the cluster root gives: accen-dev is shared with the co-tenant Packt project,
  # and a default applies silently into whichever account it names.
  description = "AWS profile of the account to place the boundary in. Required."
}

# Keep in step with local.permissions_boundary_name in ../../terraform/aws/cluster/main.tf and with
# BOUNDARY_NAME in ../pipeline.py. The structural check fails any role whose boundary is not this name.
locals {
  boundary_name = "watch-it-burn-permissions-boundary"
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

resource "aws_iam_policy" "permissions_boundary" {
  name        = local.boundary_name
  description = "Ceiling for every Watch It Burn workload role: no IAM escalation, no org/account, no public S3, no audit tampering."
  policy = templatefile("${path.module}/../permissions-boundary.json.tftpl", {
    account_id    = data.aws_caller_identity.current.account_id
    partition     = data.aws_partition.current.partition
    boundary_name = local.boundary_name
  })
}

output "permissions_boundary_arn" {
  value = aws_iam_policy.permissions_boundary.arn
}
