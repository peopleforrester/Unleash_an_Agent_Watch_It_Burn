# ABOUTME: The shared lab VPC, provisioned once. Every attendee cluster attaches to its
# ABOUTME: subnets, so the whole fleet shares one VPC and one NAT instead of one each.
#
# Modeled on the Packt sister repo's lab-vpc (proven for this exact shape on the same shared
# AWS account). Sized for VPC-CNI prefix delegation, which is the real constraint: a node with
# maxPods=110 consumes ~112 IPs (7x /28 prefixes). /18 private subnets (16,384 IPs each) hold
# ~60 concurrent attendee clusters with headroom. One shared NAT keeps cost flat instead of one
# NAT per cluster. This is a 2-hour lab, not production multi-tenancy: isolation between attendee
# clusters is in-cluster (NetworkPolicy / Kyverno), not at the VPC.

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
  # Collision-avoidance: this AWS account is SHARED with the Packt project. Every resource we
  # create carries project=watch-it-burn so ours are unambiguous and cleanup/discovery is by tag,
  # never by guessing. (Packt tags Workshop=packt; we never touch anything not tagged ours.)
  default_tags {
    tags = {
      project   = "watch-it-burn"
      event     = "ai-engineer-worldsfair-2026"
      Purpose   = "lab-shared-vpc"
      ManagedBy = "terraform"
    }
  }
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "profile" {
  type    = string
  default = "accen-dev"
}

data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "watch-it-burn-lab-vpc"
  cidr = "10.0.0.0/16"

  azs = local.azs
  # /18 private subnets: room for prefix-delegated nodes across ~60 concurrent clusters.
  private_subnets = ["10.0.0.0/18", "10.0.64.0/18"]
  # Small public subnets just for the shared NAT and any public LBs.
  public_subnets = ["10.0.128.0/24", "10.0.129.0/24"]

  # One shared NAT for the whole lab fleet, not one per cluster.
  enable_nat_gateway = true
  single_nat_gateway = true

  # Subnet discovery tags so every cluster's AWS Load Balancer Controller finds them. Role tags
  # are deliberately the ONLY discovery tags: in a shared VPC the controller discovers subnets by
  # role and all clusters use the same subnets. A per-cluster kubernetes.io/cluster/<name> tag is
  # neither required (EKS relaxed it) nor correct on a shared subnet, so it is intentionally absent.
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }
}

# Bedrock VPC endpoint (PrivateLink) — the load-bearing half of the Attack-1 (exfil) control.
# The agent reaches Bedrock through this in-VPC ENI (an address in the VPC CIDR), so the
# agent-namespace egress allowlist (policies/network-policies/per-namespace/agent-egress-allowlist.yaml,
# in-VPC 10.0.0.0/16 only) permits Bedrock while denying S3 PutObject, which has no endpoint and so
# egresses to the public internet, where there is no allow. private_dns_enabled makes the public
# hostname bedrock-runtime.<region>.amazonaws.com resolve to this ENI from inside the VPC.
#
# Intentionally NO S3 endpoint. An S3 GATEWAY endpoint would route S3 via the VPC route table to an
# AWS-managed prefix list — that traffic looks in-VPC at L3 and the CIDR allow could not distinguish
# it, defeating the control. The terraform-aws-modules/vpc module above creates no endpoints, so the
# only endpoint in this VPC is the Bedrock one below. Keep it that way.
resource "aws_security_group" "bedrock_vpce" {
  name        = "watch-it-burn-bedrock-vpce"
  description = "Allow 443 from the lab VPC to the Bedrock interface endpoint"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from anywhere in the lab VPC (attendee/instructor clusters)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [module.vpc.vpc_cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "watch-it-burn-bedrock-vpce" }
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = module.vpc.private_subnets
  security_group_ids  = [aws_security_group.bedrock_vpce.id]
  private_dns_enabled = true

  tags = { Name = "watch-it-burn-bedrock-runtime" }
}

output "bedrock_vpce_id" {
  value = aws_vpc_endpoint.bedrock_runtime.id
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnet_ids" {
  value = module.vpc.private_subnets
}

output "region" {
  value = var.region
}
