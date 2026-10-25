# ABOUTME: One attendee EKS cluster, attached to the shared lab VPC. Instantiated once per
# ABOUTME: attendee by the fleet driver, each with its own state. Independent take-home cluster.
#
# Modeled on the Packt sister repo's cluster/ module (proven shape on the same shared account):
# takes vpc_id + private_subnet_ids as inputs (no VPC of its own), VPC-CNI prefix delegation +
# maxPods=110, and create_cloudwatch_log_group=false so reprovision is idempotent. Diverges from Packt:
# EBS CSI + LB controller + ESO + agent are ALL on Pod Identity (no IRSA/OIDC provider on the cluster).
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
    tags = local.fleet_tags
  }
}

# The same tag set the provider applies by default, named so it can ALSO be attached by the mechanisms
# default_tags does not reach. That gap is not theoretical: an audit of one 50-cluster account on the
# sister fleet found 451 resources carrying no project tag at all, most of them node volumes, CNI
# network interfaces and CSI-provisioned PVC volumes. Anything a teardown sweep selects by tag misses
# those, so they keep billing after the event, and a sweep that widens its selector to compensate is
# how a shared account loses a co-tenant's resources.
locals {
  fleet_tags = {
    project   = "watch-it-burn"
    event     = var.event
    Purpose   = "attendee-cluster"
    ManagedBy = "terraform"
    attendee  = var.name
  }
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "event" {
  type = string
  # NO DEFAULT, on purpose (#494). Spend is split per event by this tag, and it used to be a literal here,
  # so clusters built for the next event were still tagged with the last one and billed into its bucket.
  # The value is set once, in fleet/event.sh, and the fleet driver passes it on every apply and destroy.
  description = "Event this cluster is billed to (the event= tag), e.g. kubecon-na-2026. Set in fleet/event.sh."
  validation {
    condition     = can(regex("^[a-z0-9]+(-[a-z0-9]+)*$", var.event))
    error_message = "event must be a lowercase-hyphenated slug such as kubecon-na-2026."
  }
}

variable "profile" {
  type = string
  # NO DEFAULT, on purpose. Clusters are applied across five accounts, and accen-dev is SHARED with the
  # co-tenant Packt project. A default means any code path that forgets -var profile= silently applies
  # into that account instead of failing, where the clusters are then invisible to the intended
  # account's teardown and keep billing. Failing loudly is the cheaper outcome.
  description = "AWS profile that owns this cluster. Required; the fleet driver always passes it."
}

variable "name" {
  type        = string
  description = "Unique cluster name, one per attendee (e.g. watch-it-burn-attendee-001)."
}

variable "kubernetes_version" {
  type    = string
  default = "1.36"
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

# The canonical permissions boundary (#207). Every IAM role this root creates carries it: the cluster role,
# the node role and each Pod Identity role. It is created once per account by infra/org/boundary, not here,
# so its ARN is known at plan time and no CreateRole can race it. An account where that root was never
# applied fails right here at plan ("no matching IAM Policy found"), before any unbounded role exists.
# The policy pipeline (infra/org/pipeline.py, structural check) fails any role whose boundary is not this.
locals {
  permissions_boundary_name = "watch-it-burn-permissions-boundary"
}

data "aws_iam_policy" "permissions_boundary" {
  name = local.permissions_boundary_name
}

# Every registry module here is pinned to its minor (~> X.Y.0). .terraform.lock.hcl locks providers but
# not modules, so a looser range let a fresh init pick up a newer module whose higher aws floor (21.29.0
# needs >= 6.59.0) no longer fit the committed lock, and init failed (#468). Moving a module's minor is
# now a deliberate edit, made together with `terraform init -upgrade` and the regenerated lock.
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.29.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  endpoint_public_access                   = true
  enable_cluster_creator_admin_permissions = true
  # No IRSA/OIDC provider: every IAM-needing workload (LB controller, ESO, EBS CSI, agent) is on Pod
  # Identity now, so nothing is left to trust an OIDC provider. Dropping it removes the per-cluster OIDC
  # endpoint entirely, fleet-consistent with the "no per-cluster OIDC trust" pattern used below.
  enable_irsa = false

  iam_role_permissions_boundary = data.aws_iam_policy.permissions_boundary.arn

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
          # The CNI creates the pod ENIs itself, so provider default_tags never touch them. Prefix
          # delegation means MORE of them, not fewer: the sister fleet measured ~200 untagged network
          # interfaces per 50-cluster account before setting this. Untagged ENIs are the ones that pin
          # a subnet and make DeleteVpc fail at teardown, while being invisible to a tag-driven sweep.
          ADDITIONAL_ENI_TAGS = jsonencode(local.fleet_tags)
        }
      })
    }
    kube-proxy = {
      before_compute = true
    }
    coredns                = {}
    eks-pod-identity-agent = {}
    # EBS CSI creds via Pod Identity (module.ebs_csi_pod_identity binds kube-system:ebs-csi-controller-sa).
    # No service_account_role_arn -> the driver SA gets creds from the pod-identity-agent, not IRSA/OIDC.
    aws-ebs-csi-driver = {}
  }

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.instance_types
      min_size       = var.node_min_size
      max_size       = var.node_max_size
      desired_size   = var.node_desired_size

      iam_role_permissions_boundary = data.aws_iam_policy.permissions_boundary.arn
      # Force the rolling update past pod-eviction blockers. On a single-node cluster the IDP's
      # PodDisruptionBudgets (ArgoCD/Prometheus/etc., minAvailable:1) make a node drain unsatisfiable,
      # so a launch-template change (e.g. the disk fix) wedges with PodEvictionFailure. These clusters
      # are disposable, so force the update rather than respecting PDBs during a node roll. (Fresh
      # provisions never roll, so the event path is unaffected; this only matters for config changes.)
      force_update_version = true
      # Managed node groups do NOT propagate the provider's default_tags to the EC2 instances or to
      # their root volumes: launch-template tag_specifications are DATA INSIDE the template, not
      # resources the provider tags. Without both of these the node and its 100 GiB root disk carry no
      # project tag, so a tag-scoped sweep cannot see them and they bill on after teardown.
      launch_template_tags = local.fleet_tags
      tag_specifications   = ["instance", "volume", "network-interface"]
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

# EBS CSI on Pod Identity (rolled over from IRSA 2026-07-18). Same fleet-safe pattern as the LB/ESO/agent
# roles: a per-cluster role + association, no SA annotation, no OIDC trust. attach_aws_ebs_csi_policy grants
# the standard EBS volume-management permissions (AWS-managed EBS CSI policy equivalent); the workshop gp3
# volumes use the default aws/ebs KMS key, which that policy covers, so no aws_ebs_csi_kms_arns is needed.
module "ebs_csi_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12.0"

  permissions_boundary_arn = data.aws_iam_policy.permissions_boundary.arn

  name                      = "${var.name}-ebs-csi"
  attach_aws_ebs_csi_policy = true

  associations = {
    main = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "ebs-csi-controller-sa"
    }
  }
}

# Pod Identity for the AWS Load Balancer Controller (Packt pattern: a reusable role + a per-cluster
# association instead of 60 OIDC trust policies). The Helm chart creates the SA in kube-system.
module "aws_lb_controller_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12.0"

  permissions_boundary_arn = data.aws_iam_policy.permissions_boundary.arn

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
  version = "~> 1.12.0"

  permissions_boundary_arn = data.aws_iam_policy.permissions_boundary.arn

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
# The four models the workshop can actually bind, as cross-region inference profiles. Nova Pro is the
# default; the three Claude tiers exist for the cost-race demo. Keep in sync with the ModelConfigs in
# gitops/ai-layer/resources.yaml: a model listed there and missing here fails at invoke time with an
# AccessDenied that looks like a Bedrock outage rather than a policy gap.
locals {
  # Keyed by guard-proxy's MODEL_TIER names (_TIER_TO_MODEL_ID in its proxy.py), which also name each
  # cluster's application inference profile below: <cluster>-nova, <cluster>-haiku, ...
  bedrock_tiers = {
    nova   = "us.amazon.nova-pro-v1:0"
    haiku  = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    sonnet = "us.anthropic.claude-sonnet-4-6"
    opus   = "us.anthropic.claude-opus-4-8"
  }
  bedrock_profiles = values(local.bedrock_tiers)
  # The SAME ids without the "us." routing prefix. A cross-region profile fans out to foundation models
  # in several regions, and the caller needs permission on BOTH the profile and every underlying model
  # ARN. Measured on us.amazon.nova-pro-v1:0, which resolves to foundation models in us-east-1, us-west-2
  # AND us-east-2. Granting only the profile ARN produces AccessDenied on every request, so a "tighter"
  # policy that omits these does not harden the agent, it breaks it.
  bedrock_models = [for p in local.bedrock_profiles : replace(p, "us.", "")]
}

# Model spend carries project/event (#513). A system-defined profile (us.amazon.nova-pro-v1:0) cannot be
# tagged, so every call through one bills untagged whatever the cost-allocation tags are set to, and the
# denial-of-wallet numbers on stage could not be checked against the bill. An application inference profile
# copied from it routes to the same foundation models in the same regions and carries this cluster's tags,
# so Bedrock spend splits by event and by attendee like the rest of the cluster's bill.
#
# One per tier per cluster. The ARN ends in an id Bedrock picks, so the gitops ModelConfigs cannot name it:
# they keep the system profile id, which stays the pin (model_pin_check.py, guard-proxy's MODEL_TIER), and
# fleet.sh pin_bedrock_profiles points each live Bedrock ModelConfig at this cluster's ARN from the output
# below. `consumer` keeps the agent's grant off the tutor's profile and the other way round.
resource "aws_bedrock_inference_profile" "agent" {
  for_each = local.bedrock_tiers

  name        = "${var.name}-${each.key}"
  description = "Watch It Burn agent on ${var.name}: ${each.value}, tagged for cost allocation."
  model_source {
    copy_from = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${each.value}"
  }
  tags = merge(local.fleet_tags, { consumer = "agent" })
}

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
      # SCOPED, was Resource = "*" (#138). An attendee holds cluster-admin on their own cluster, so they
      # can schedule a pod under the agent's service account and reach Bedrock directly, around the
      # guard-proxy and its cost cap. That path cannot be closed from the proxy, which is the point of
      # the challenge; what CAN be closed is what the bypass reaches once it is there. With "*" it was
      # every model enabled in the account. It is now the four the workshop binds, so a bypass cannot
      # discover a more expensive model than the ones already on the menu.
      #
      # Region wildcards are deliberate: the profile is regional to this account and the foundation
      # models are region-less in the ARN but fan out across regions, so pinning either would break the
      # cross-region routing the profiles exist to provide.
      Resource = concat(
        [for p in local.bedrock_profiles :
        "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/${p}"],
        [for m in local.bedrock_models : "arn:aws:bedrock:*::foundation-model/${m}"],
      )
      # Only a pod in the agent namespace of THIS cluster can use the grant. EKS Pod Identity puts these
      # on every session as session tags (the module's trust policy allows sts:TagSession), so a session
      # taken by some other path, or for some other cluster's association, holds the role and still cannot
      # invoke. It is also what the policy pipeline's structural check asks of every Allow (#207).
      Condition = {
        StringEquals = {
          "aws:PrincipalTag/eks-cluster-name"     = var.name
          "aws:PrincipalTag/kubernetes-namespace" = "agent"
        }
      }
      }, {
      # This cluster's tagged application profiles (#513), which is what the ModelConfigs call. Matched by
      # the profiles' own tags rather than their ARNs: the ARNs are known only after apply, and a policy
      # document unknown at plan is one the policy pipeline cannot check. The statement above still has to
      # hold, because a call through an application profile is authorized on the foundation models too.
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
      ]
      Resource = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:application-inference-profile/*"
      Condition = {
        StringEquals = {
          "aws:PrincipalTag/eks-cluster-name"     = var.name
          "aws:PrincipalTag/kubernetes-namespace" = "agent"
          "aws:ResourceTag/project"               = local.fleet_tags.project
          "aws:ResourceTag/attendee"              = var.name
          "aws:ResourceTag/consumer"              = "agent"
        }
      }
    }]
  })
}

module "agent_bedrock_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12.0"

  permissions_boundary_arn = data.aws_iam_policy.permissions_boundary.arn

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
    # agentgateway signs its own Bedrock calls (#394). Its inference bind on :3002 fronts Bedrock for
    # kagent, and the bedrock provider supplies implicit AWS auth by itself: agentgateway v1.5.0's
    # AIProvider::Bedrock arm of default_connector_policies sets BackendAuthKind::Aws(Implicit), which
    # resolves through aws_config::load_defaults and therefore through Pod Identity. There is no config
    # key to add and none was missing; what was missing is a credential for the gateway's own
    # ServiceAccount to find. Same policy as the agent, because the two call the same four models: a
    # second policy would only be a second thing to keep in step.
    gateway = {
      cluster_name    = module.eks.cluster_name
      namespace       = "agent"
      service_account = "agentgateway"
    }
  }
}

# --- Workshop tutor -----------------------------------------------------------------------------
#
# The in-workbench tutor runs inside the web-terminal pod and reaches Bedrock through Pod Identity, so
# there is no key in an image, in a Secret, or in a student-controlled cluster: nothing to rotate and
# nothing to leak. The grant exists the moment the cluster exists, because it is created by the same
# terraform that creates the cluster, which is what makes the tutor part of the lab rather than a
# separate service somebody has to stand up.
#
# Scoped deliberately tighter than the agent's own Bedrock policy above, which is Resource = "*". This
# one is read-only inference on ONE model family. A cluster-admin's reach is the union of every Pod
# Identity role on the cluster, so a broad grant here would widen what the workshop's own hostile
# workloads can do, and this cluster runs those on purpose.
data "aws_caller_identity" "current" {}

resource "aws_iam_policy" "tutor_bedrock_invoke" {
  name        = "${var.name}-tutor-bedrock"
  description = "Bedrock inference for the in-workbench workshop tutor on ${var.name}. Sonnet only."
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
      # Both halves are required for a cross-region inference profile: the profile itself, and the
      # foundation models in whichever region it routes to (hence the wildcard region on the second).
      Resource = [
        "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.tutor_model}",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-*",
      ]
      # The tutor's one ServiceAccount on this cluster, by Pod Identity session tag; see bedrock_invoke.
      Condition = {
        StringEquals = {
          "aws:PrincipalTag/eks-cluster-name"           = var.name
          "aws:PrincipalTag/kubernetes-namespace"       = "agent"
          "aws:PrincipalTag/kubernetes-service-account" = "web-terminal"
        }
      }
      }, {
      # The tutor's tagged application profile (#513), matched by its tags for the reason given on
      # bedrock_invoke. consumer = "tutor" keeps this grant on the tutor's one profile: the agent's four
      # carry consumer = "agent", so Sonnet-only still holds.
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
      ]
      Resource = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:application-inference-profile/*"
      Condition = {
        StringEquals = {
          "aws:PrincipalTag/eks-cluster-name"           = var.name
          "aws:PrincipalTag/kubernetes-namespace"       = "agent"
          "aws:PrincipalTag/kubernetes-service-account" = "web-terminal"
          "aws:ResourceTag/project"                     = local.fleet_tags.project
          "aws:ResourceTag/attendee"                    = var.name
          "aws:ResourceTag/consumer"                    = "tutor"
        }
      }
    }]
  })
}

variable "tutor_model" {
  description = "Bedrock inference profile the workshop tutor uses. Verified ACTIVE in us-west-2 on 2026-08-24."
  type        = string
  default     = "us.anthropic.claude-sonnet-5"
}

# The tutor's spend is tagged the same way as the agent's (#513). No tutor runs today (the web terminal's
# entrypoint removed it, #89), so nothing calls this yet; a replacement calls tutor_bedrock_profile_arn,
# not var.tutor_model, or its spend lands untagged again.
resource "aws_bedrock_inference_profile" "tutor" {
  name        = "${var.name}-tutor"
  description = "Watch It Burn workshop tutor on ${var.name}: ${var.tutor_model}, tagged for cost allocation."
  model_source {
    copy_from = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.tutor_model}"
  }
  tags = merge(local.fleet_tags, { consumer = "tutor" })
}

module "tutor_bedrock_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12.0"

  permissions_boundary_arn = data.aws_iam_policy.permissions_boundary.arn

  # Short name for the same 38-char name_prefix cap that forced "<cluster>-bedrock-" above.
  name                   = "${var.name}-tutor"
  additional_policy_arns = { tutor_bedrock = aws_iam_policy.tutor_bedrock_invoke.arn }

  associations = {
    main = {
      cluster_name    = module.eks.cluster_name
      namespace       = "agent"
      service_account = "web-terminal"
    }
  }
}

# --- Attendee IAM user ------------------------------------------------------------------------------
#
# The student's own AWS identity: one IAM user per cluster, whose access key the fleet driver mints after
# apply and hands to the web terminal and the pool row. Its inline policy reaches this cluster and nothing
# else, so `aws eks update-kubeconfig` works for theirs and no one else's. The access entry below is what
# makes kubectl work once the kubeconfig is written.
#
# It used to be made by provisioning-agenticburn's generate_attendee_aws.py with put_user_policy, so the
# policy pipeline never saw the document and the user carried no boundary (#549). Here it is planned like
# every other grant: checks 1 to 4 read it from the plan, and the boundary caps the user as it caps the roles.
locals {
  # Kept in step with iam_user_for() in fleet/fleet.sh, which finds this user to mint its key and to sweep it.
  # IAM caps a user name at 64; substr returns the whole string when it is shorter.
  attendee_user = substr("wib-${trimprefix(var.name, "watch-it-burn-")}", 0, 64)
}

resource "aws_iam_user" "attendee" {
  name                 = local.attendee_user
  permissions_boundary = data.aws_iam_policy.permissions_boundary.arn
  # The access key is minted outside Terraform (its secret would otherwise sit in the state file), so a
  # destroy must be able to delete a user that still holds one.
  force_destroy = true
  # cluster= is what fleet.sh's teardown sweeps match on (#458); project= comes from default_tags.
  tags = { cluster = var.name }
}

resource "aws_iam_user_policy" "attendee_eks" {
  name = "eks-own-cluster"
  user = aws_iam_user.attendee.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DescribeOwnCluster"
      Effect   = "Allow"
      Action   = ["eks:DescribeCluster"]
      Resource = "arn:aws:eks:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.name}"
      # Restates the ARN's region. It is here because check 3 asks every Allow for a scoping key (#207).
      Condition = { StringEquals = { "aws:RequestedRegion" = var.region } }
      }, {
      Sid    = "ListClusters"
      Effect = "Allow"
      Action = ["eks:ListClusters"]
      # ListClusters takes no resource ARN (waived in infra/org/exceptions.md); the region is what scopes it.
      Resource  = "*"
      Condition = { StringEquals = { "aws:RequestedRegion" = var.region } }
    }]
  })
}

resource "aws_eks_access_entry" "attendee" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_user.attendee.arn
  type          = "STANDARD"
}

# Cluster admin on their own cluster is the workshop's premise: the student is the platform team.
resource "aws_eks_access_policy_association" "attendee_admin" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_user.attendee.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope {
    type = "cluster"
  }
  depends_on = [aws_eks_access_entry.attendee]
}

output "attendee_iam_user" {
  value = aws_iam_user.attendee.name
}

output "tutor_bedrock_role_arn" {
  value = module.tutor_bedrock_pod_identity.iam_role_arn
}

output "tutor_bedrock_profile_arn" {
  value = aws_bedrock_inference_profile.tutor.arn
}

# System profile id -> this cluster's application profile ARN. fleet.sh pin_bedrock_profiles reads this to
# point each Bedrock ModelConfig (which commits the system id) at the tagged profile (#513).
output "bedrock_application_profiles" {
  value = { for tier, p in aws_bedrock_inference_profile.agent : local.bedrock_tiers[tier] => p.arn }
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
