# ABOUTME: One attendee EKS cluster, attached to the shared lab VPC. Instantiated once per
# ABOUTME: attendee by the fleet driver, each with its own state. Independent take-home cluster.
#
# Modeled on the Packt sister repo's cluster/ module (proven shape on the same shared account):
# takes vpc_id + private_subnet_ids as inputs (no VPC of its own), VPC-CNI prefix delegation +
# maxPods=110, EBS CSI via IRSA, Pod Identity for the AWS LB controller, and
# create_cloudwatch_log_group=false so reprovision is idempotent.
#
# THREE Watch-It-Burn deltas vs Packt (our controls; Packt does not have these):
#   1. podPidsLimit=1024 in the node NodeConfig  -> the fork-bomb cap (verified live on EKS).
#   2. enableNetworkPolicy="true" in vpc-cni     -> the egress default-deny/allowlist beat.
#   3. Pod Identity for agent:agent-sa -> Bedrock -> the kagent agent's model access, fleet-safe
#      (a reusable role + per-cluster association, not 60 OIDC trust policies / SA annotations).

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
      event     = "ai-engineer-worldsfair-2026"
      Purpose   = "attendee-cluster"
      ManagedBy = "terraform"
      attendee  = var.name
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

variable "name" {
  type        = string
  description = "Unique cluster name, one per attendee (e.g. watch-it-burn-attendee-001)."
}

variable "kubernetes_version" {
  type    = string
  default = "1.35"
}

variable "vpc_id" {
  type        = string
  description = "Shared lab VPC id (from the lab-vpc root)."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Shared lab private subnet ids (from the lab-vpc root)."
}

# Node sizing. Default mirrors Packt's validated single-node AI-platform shape (1x t3.2xlarge +
# prefix delegation). verify-at-build: the full Watch It Burn IDP (Istio, Kyverno, Falco DaemonSet,
# ESO, cert-manager, ArgoCD, observability, kagent + AI layer, burn targets) was validated on a
# 6x t3.large test cluster; confirm it fits the chosen attendee node and bump instance_types or
# node count if pods stay Pending. Conservative start, scale up only if necessary.
variable "instance_types" {
  type    = list(string)
  default = ["t3.2xlarge"]
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 1
}

variable "node_desired_size" {
  type    = number
  default = 1
}

# The per-pod PID cap (cgroup pids.max). This is the ONLY thing that inline-blocks a fork bomb
# (the kernel returns -EAGAIN at the cap); Falco+Talon are detect-and-respond on top. Verified
# live on EKS: pod-cgroup pids.max=1024, a fork bomb hits "can't fork: Resource temporarily
# unavailable" and the node stays Ready.
# Set to -1 for NO per-pod cap (kubelet's uncapped default): the fork bomb then exhausts node PIDs
# and takes the cluster down. fleet.sh passes -1 for Round-1 burn clusters so C4 lands as the burn;
# R2/R3 and attendee clusters keep this 1024 default so the cap is the working defense.
variable "pod_pids_limit" {
  type    = number
  default = 1024
}

# Docker Hub Team auth, baked into the node so every docker.io pull authenticates at the node level.
# Anonymous Docker Hub pulls are rate-limited (~100/6h per NAT IP); at fleet scale (50/account behind
# one NAT) that yields 429 ImagePullBackOff across the IDP image set. With this set, the node's
# containerd presents the peopleforrester Team PAT to registry-1.docker.io and the limit becomes the
# Team plan's, not anonymous. Value is base64("user:pat"). Empty disables the registry config entirely
# (a bare apply still works); fleet.sh supplies it from ~/secrets (mrf-secrets). NEVER hardcode it here.
variable "dockerhub_auth_b64" {
  type      = string
  default   = ""
  sensitive = true
}

# Root volume size (GiB). MUST be set via block_device_mappings below, NOT the node group's disk_size:
# cloudinit_pre_nodeadm (for the PID cap) forces a custom launch template, and disk_size is silently
# ignored with a custom LT -> the node falls back to the AL2023 default 20 GiB, which trips DiskPressure
# under this image-heavy IDP and leaves pods Pending (found live on watch-it-burn-attendee-001). 100 GiB
# holds the full image set + logs + the attendee burn workloads with headroom; gp3 is cheap + ephemeral.
variable "node_disk_size" {
  type    = number
  default = 100
}

locals {
  # NodeConfig part: maxPods + the fork-bomb pod-pids cap (the Watch It Burn delta). Always present.
  nodeadm_part = {
    content_type = "application/node.eks.aws"
    content      = <<-EOT
      apiVersion: node.eks.aws/v1alpha1
      kind: NodeConfig
      spec:
        kubelet:
          config:
            maxPods: 110
            podPidsLimit: ${var.pod_pids_limit}
    EOT
  }

  # Node-level containerd registry config for docker.io, written to /etc/containerd/certs.d/docker.io/hosts.toml.
  # AL2023 EKS already sets containerd registry config_path = /etc/containerd/certs.d, so dropping this file is
  # enough; no config.toml merge (lower bootstrap risk). containerd reads hosts.toml per-pull and tries hosts in
  # listed order:
  #   1. registry-1.docker.io WITH the peopleforrester Team PAT (Basic auth) => authenticated pulls, no anon 429.
  #   2. ghcr.io/peopleforrester/dockerhub (path-preserving mirror, override_path) => automatic fallback if Docker
  #      Hub errors (429/outage). Mirror copies are maintained by the fleet mirror step (crane).
  # Only emitted when dockerhub_auth_b64 is set; a bare apply omits the part. b64-encode the file content so the
  # embedded auth header survives cloud-config YAML untouched.
  # nonsensitive() on the auth ref is REQUIRED: dockerhub_auth_b64 is a sensitive variable, and it flows
  # through here into cloudinit_pre_nodeadm -> eks_managed_node_groups. The terraform-aws-eks module does
  # for_each over that map, and for_each rejects a sensitive-derived map ("Invalid for_each argument:
  # Sensitive values ... cannot be used as for_each arguments"), which failed every fleet apply. The auth
  # lands in node user-data on the instance regardless, so stripping the sensitivity marker here is moot.
  dockerhub_hosts_toml = <<-EOT
    server = "https://registry-1.docker.io"

    [host."https://registry-1.docker.io"]
      capabilities = ["pull", "resolve"]
      [host."https://registry-1.docker.io".header]
        authorization = "Basic ${nonsensitive(var.dockerhub_auth_b64)}"

    [host."https://ghcr.io/v2/peopleforrester/dockerhub"]
      capabilities = ["pull", "resolve"]
      override_path = true
  EOT

  dockerhub_part = {
    content_type = "text/cloud-config"
    content      = <<-EOT
      #cloud-config
      write_files:
        - path: /etc/containerd/certs.d/docker.io/hosts.toml
          permissions: '0600'
          encoding: b64
          content: ${base64encode(local.dockerhub_hosts_toml)}
    EOT
  }

  # nonsensitive() on the condition too: a ternary whose CONDITION derives from a sensitive value yields
  # a sensitive result, which would re-taint cloudinit_parts -> the node-group map -> the module for_each.
  cloudinit_parts = nonsensitive(var.dockerhub_auth_b64) == "" ? [local.nodeadm_part] : [local.nodeadm_part, local.dockerhub_part]
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  endpoint_public_access                   = true
  enable_cluster_creator_admin_permissions = true
  enable_irsa                              = true

  # EKS auto-creates the control-plane log group and it survives destroy; let EKS own it so a
  # reused name never collides with "already exists" on reprovision. (Orphans are swept by
  # fleet/cleanup-log-groups.sh, scoped to our cluster-name prefix.)
  create_cloudwatch_log_group = false

  vpc_id     = var.vpc_id
  subnet_ids = var.private_subnet_ids

  addons = {
    vpc-cni = {
      before_compute = true
      # Prefix delegation raises t3.2xlarge from 58 to ~110 pods so the platform fits one node.
      # enableNetworkPolicy is the Watch It Burn delta: VPC-CNI enforces NetworkPolicy in-kernel,
      # which the egress beat (default-deny + allowlist) depends on. Without it, policies are inert
      # (found live on watch-it-burn-test). Pairs with the node group maxPods=110 below.
      configuration_values = jsonencode({
        enableNetworkPolicy = "true"
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
    kube-proxy = {
      before_compute = true
    }
    coredns                = {}
    eks-pod-identity-agent = {}
    aws-ebs-csi-driver = {
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.instance_types
      min_size       = var.node_min_size
      max_size       = var.node_max_size
      desired_size   = var.node_desired_size
      # Force the rolling update past pod-eviction blockers. On a single-node cluster the IDP's
      # PodDisruptionBudgets (ArgoCD/Prometheus/etc., minAvailable:1) make a node drain unsatisfiable,
      # so a launch-template change (e.g. the disk fix) wedges with PodEvictionFailure. These clusters
      # are disposable, so force the update rather than respecting PDBs during a node roll. (Fresh
      # provisions never roll, so the event path is unaffected; this only matters for config changes.)
      force_update_version = true
      # IMDS hardening (PRD 35 3.7-A): the agent runs run_shell by design, so a pod that can reach node
      # IMDS could steal the node instance-role creds (broader than the pod's Bedrock-scoped Pod Identity),
      # which would falsify PRD 36's "AWS keyless, nothing to steal" baseline. Require IMDSv2 and set
      # hop_limit=1 so pods cannot reach node IMDS. Pod Identity is unaffected: it uses the container-creds
      # endpoint 169.254.170.23, not IMDS. verify-at-build: confirm Pod Identity still resolves at hop=1.
      metadata_options = {
        http_endpoint               = "enabled"
        http_tokens                 = "required"
        http_put_response_hop_limit = 1
      }
      # Root volume via block_device_mappings, NOT disk_size: cloudinit_pre_nodeadm forces a custom
      # launch template, under which the module ignores disk_size (node would fall back to AL2023's
      # 20 GiB default and hit DiskPressure). See the node_disk_size variable for the why.
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = var.node_disk_size
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }
      # AL2023 nodeadm ignores prefix delegation when computing max-pods, so set it explicitly.
      # podPidsLimit is the Watch It Burn delta: the fork-bomb cap, delivered via the same nodeadm
      # NodeConfig (eksctl delivered this via overrideBootstrapCommand; Terraform via cloudinit_pre_nodeadm).
      # NodeConfig (maxPods + fork-bomb pod-pids cap) plus, when fleet supplies dockerhub_auth_b64, a
      # cloud-config part that writes the docker.io containerd registry config (Team auth + GHCR fallback).
      # See locals.nodeadm_part / locals.dockerhub_part above.
      cloudinit_pre_nodeadm = local.cloudinit_parts
    }
  }
}

module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name             = "${var.name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }
}

# Pod Identity for the AWS Load Balancer Controller (Packt pattern: a reusable role + a per-cluster
# association instead of 60 OIDC trust policies). The Helm chart creates the SA in kube-system.
module "aws_lb_controller_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.0"

  name                            = "${var.name}-aws-lbc"
  attach_aws_lb_controller_policy = true

  associations = {
    main = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
    }
  }
}

# Pod Identity for External Secrets Operator (platform:external-secrets) -> AWS Secrets Manager.
# Same fleet-safe pattern as the agent/LB roles: a per-cluster role + association, no SA IRSA
# annotation, no per-cluster OIDC trust. Replaces the prior IRSA role (modern June-2026 convention).
module "eso_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.0"

  name                           = "${var.name}-eso"
  attach_external_secrets_policy = true
  # The module gates the secretsmanager:GetSecretValue/DescribeSecret statement on this ARN list being
  # non-empty (see external_secrets.tf: for_each = length(...secrets_manager_arns) > 0). Without it the
  # role can create an AWS client but every GetSecretValue is AccessDenied ("no identity-based policy
  # allows the action"). Scope to the workshop secret prefix; region/account wildcarded so the same role
  # definition is fleet-safe across all clusters. All workshop secrets use the `watch-it-burn/` prefix
  # (e.g. watch-it-burn/grafana-admin, watch-it-burn/test-secret, watch-it-burn/datadog).
  external_secrets_secrets_manager_arns = ["arn:aws:secretsmanager:*:*:secret:watch-it-burn/*"]

  associations = {
    main = {
      cluster_name    = module.eks.cluster_name
      namespace       = "platform"
      service_account = "external-secrets"
    }
  }
}

# Bedrock access for the kagent agent (agent:agent-sa). Pod Identity, not IRSA, so the fleet binds
# a per-cluster role to the SA with NO ServiceAccount annotation in gitops (the gitops manifests are
# identical across all 60 clusters) and NO per-cluster OIDC trust. The eks-pod-identity-agent addon
# (above) injects the creds via the standard AWS SDK chain, which kagent already uses for Bedrock.
# verify-at-build: we validated the IRSA path live; confirm kagent picks up Pod Identity creds on a
# real cluster (same SDK chain; high confidence). Fall back to IRSA + a fleet annotate step if not.
resource "aws_iam_policy" "bedrock_invoke" {
  name        = "${var.name}-bedrock-invoke"
  description = "Bedrock model invocation for the Watch It Burn agent on ${var.name}."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
      ]
      Resource = "*"
    }]
  })
}

module "agent_bedrock_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.0"

  # Name kept short: the module derives the IAM role from name_prefix = "${name}-", which is capped
  # at 38 chars. "<cluster>-agent-bedrock-" overran it (40>38); "<cluster>-bedrock-" fits.
  name                   = "${var.name}-bedrock"
  additional_policy_arns = { bedrock = aws_iam_policy.bedrock_invoke.arn }

  associations = {
    main = {
      cluster_name    = module.eks.cluster_name
      namespace       = "agent"
      service_account = "agent-sa"
    }
  }
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "agent_bedrock_role_arn" {
  value = module.agent_bedrock_pod_identity.iam_role_arn
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region} --profile ${var.profile} --kubeconfig /tmp/${module.eks.cluster_name}.kubeconfig"
}
