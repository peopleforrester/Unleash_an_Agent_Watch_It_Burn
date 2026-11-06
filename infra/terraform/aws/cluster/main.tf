# ABOUTME: One attendee EKS cluster, attached to the shared lab VPC. Instantiated once per
# ABOUTME: attendee by the fleet driver, each with its own state. Independent take-home cluster.
#
# Modeled on the Packt sister repo's cluster/ module (proven shape on the same shared account):
# takes vpc_id + private_subnet_ids as inputs (no VPC of its own), VPC-CNI prefix delegation +
# maxPods=110 (250 on the community cluster, #686), and create_cloudwatch_log_group=false so reprovision is idempotent. Diverges from Packt:
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
    hostname  = var.hostname
    role      = var.role
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

variable "hostname" {
  type = string
  # NO DEFAULT, on purpose (#602). lab-platform's `labctl harvest` finds the fleet by its project and event
  # tags and reads each cluster's attendee hostname from this tag (--host-tag hostname); it does not derive
  # one from the cluster name. The name is assigned upstream, by fleet.sh's public_host_for from the roster
  # and the slot grid, and the fleet driver passes it on every apply and destroy. A default would tag a
  # cluster with a host the router does not serve for it, which harvest would then hand to a student.
  description = "Public hostname this cluster is reached on (the hostname= tag), e.g. soot-sabrina.agenticburn.com, attackme.agenticburn.com or burritobot-private.agenticburn.com. Set by fleet.sh's public_host_for."
  validation {
    condition     = can(regex("^[a-z0-9]+(-[a-z0-9]+)*(\\.[a-z0-9]+(-[a-z0-9]+)*)+$", var.hostname))
    error_message = "hostname must be a lowercase DNS name such as soot-sabrina.agenticburn.com, without a scheme."
  }
}

variable "role" {
  type = string
  # NO DEFAULT, on purpose (#636). Every cluster carries the same project and event tags, so `labctl harvest`
  # finding the fleet by them would pool the roster clusters (attackme and burritobot-private) with the attendee
  # seats. This tag is what tells them apart: attendee for a seat, community or admin for a roster cluster, from
  # fleet.sh's role_for_cluster. A default would tag a roster cluster as a seat, which harvest hands to a student.
  description = "What this cluster is for (the role= tag): attendee for a seat in the pool, community or admin for a roster cluster. Set by fleet.sh's role_for_cluster."
  validation {
    condition     = contains(["attendee", "community", "admin"], var.role)
    error_message = "role must be attendee, community or admin."
  }
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

# The subnets the node group may place its node in. Null keeps every private subnet (the control plane's own
# list), which leaves a one-node cluster's zone to the Auto Scaling group. A standby (#643) passes the one
# subnet of its zone column in backups.tsv, so the standbys in a region are spread over both lab zones by
# design rather than by chance, and one zone failing cannot take every standby a role has in that region.
variable "node_subnet_ids" {
  type        = list(string)
  default     = null
  description = "Private subnet ids for the node group; null means private_subnet_ids."
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
# and takes the cluster down. fleet.sh passes -1 for the community cluster (roster.tsv) so C4 lands as
# the burn; admin and attendee clusters keep this 1024 default so the cap is the working defense.
variable "pod_pids_limit" {
  type    = number
  default = 1024
}

# The node IMDS PUT-response hop limit, the second "watch it burn" delta (#113, Michael's question-843
# call 2026-10-26). At the default 1, a pod's packet to 169.254.169.254 dies one hop short of the node's
# metadata service, so a compromised pod cannot steal the node instance-role credentials: the IMDS theft
# that turns a container compromise into a cloud-account one (ASI03 Identity & Privilege Abuse) FAILS.
# fleet.sh passes 2 for the community cluster (the unguarded spectacle, attackme.agenticburn.com), where
# the burn profile ships no agent-deny-imds ClusterNetworkPolicy either, so there the pod CAN reach node
# IMDS and `aws sts get-caller-identity` returns a node role: that is the beat where the blast radius
# leaves the cluster. admin and attendee clusters keep this 1, the working control, so the same request
# is refused and the R-vs-R contrast is real rather than narrated. Pod Identity is unaffected at either
# value: it uses the container-creds endpoint 169.254.170.23, not IMDS.
variable "imds_hop_limit" {
  type    = number
  default = 1
}

# The node's kubelet maxPods (#686). AL2023's nodeadm ignores VPC-CNI prefix delegation when it computes
# max-pods, so the NodeConfig always states it. 110 holds the whole IDP on one t3.2xlarge (AWS's recommended
# ceiling for an instance under 30 vCPUs) and is what admin and attendee clusters keep. fleet.sh passes 250 for
# the community cluster (attackme.agenticburn.com): the room's per-attendee Jokers (#685) all land on its one
# node, and at 110 with ~53 platform pods only ~55 of them fit at once. Prefix delegation gives a t3.2xlarge
# 4 ENIs x 14 slots x 16 = 896 pod IPs, so the node has addresses for all 250 and kubelet sets the cap. The
# value lives in node user data, so changing it replaces the node; it lands at the next rebuild.
variable "max_pods" {
  type    = number
  default = 110
  validation {
    condition     = var.max_pods >= 110 && var.max_pods <= 250
    error_message = "max_pods must be between 110 (the IDP's own footprint) and 250."
  }
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
  # NodeConfig part: maxPods (var.max_pods) + the fork-bomb pod-pids cap (the Watch It Burn delta). Always present.
  nodeadm_part = {
    content_type = "application/node.eks.aws"
    content      = <<-EOT
      apiVersion: node.eks.aws/v1alpha1
      kind: NodeConfig
      spec:
        kubelet:
          config:
            maxPods: ${var.max_pods}
            podPidsLimit: ${var.pod_pids_limit}
    EOT
  }

  # The NodeConfig is the only part (#714). The containerd registry config that carried the Docker Hub Team PAT,
  # with a ghcr.io fallback, is gone: no image a cluster runs is pulled from Docker Hub any more.
  cloudinit_parts = [local.nodeadm_part]
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

# The lab VPC this cluster is built in, read for its CIDR: the source of the cluster API's 443 rule below (#906).
data "aws_vpc" "lab" {
  id = var.vpc_id
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

  # The control plane reaches the workshop apps on the nodes (#869). lab-platform's attendee check, and an
  # attendee's `kubectl get --raw .../services/http:<svc>:<port>/proxy/...`, go through the API server's Service
  # proxy, which dials the app's pod from the control-plane ENIs. Those carry this module's cluster security
  # group, and the module's recommended node rules admit it only on 443, 4443, 6443, 8443, 9443, 10250 and
  # 10251. The apps listen on 8080 (the five demo apps, argocd-server, kagent-ui) and 3000 (Grafana), so every
  # probe was accepted and timed out (measured on watch-it-burn-private 2026-11-05: "dial tcp 10.0.97.64:8080:
  # connect: connection timed out"; with these two rules added by hand all eight apps answered 200). This block
  # is on module.eks itself, so every cluster the root builds gets it: attendee, admin and community alike.
  # An app on another port adds its rule here; verify/test_control_plane_app_ports.py pins the set.
  node_security_group_additional_rules = {
    ingress_cluster_8080_workshop_apps = {
      description                   = "Cluster API to node 8080/tcp workshop apps (Service proxy)"
      protocol                      = "tcp"
      from_port                     = 8080
      to_port                       = 8080
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_cluster_3000_grafana = {
      description                   = "Cluster API to node 3000/tcp Grafana (Service proxy)"
      protocol                      = "tcp"
      from_port                     = 3000
      to_port                       = 3000
      type                          = "ingress"
      source_cluster_security_group = true
    }
  }

  # The lab VPC reaches this cluster's API on 443 (#906). Every roster cluster shares the lab VPC, and with private
  # endpoint access on, the API's name resolves inside the VPC to this cluster's private endpoint ENIs, which carry
  # this module's cluster security group. The module admits only its own nodes there, so the KubeCon guardrails
  # switch, whose terminal on one cluster calls the other cluster's API through the guardrails-peer kubeconfig,
  # timed out on every peer call (measured 2026-11-05: "dial tcp 10.0.50.254:443: i/o timeout" from
  # watch-it-burn-private's terminal to watch-it-burn-community, 30 s a call), while fleet.sh guardrails-link, run
  # from outside the VPC over the public endpoint, passed. The public endpoint already admits 0.0.0.0/0
  # (publicAccessCidrs), so this opens no API a VPC host could not already reach; it only stops the private path
  # from being the one that hangs. verify/test_peer_api_rule.py pins it.
  security_group_additional_rules = {
    ingress_lab_vpc_443_api = {
      description = "Lab VPC to the cluster API on 443/tcp (the peer link of the KubeCon guardrails switch)"
      protocol    = "tcp"
      from_port   = 443
      to_port     = 443
      type        = "ingress"
      cidr_blocks = [data.aws_vpc.lab.cidr_block]
    }
  }

  addons = {
    vpc-cni = {
      before_compute = true
      # Prefix delegation lifts t3.2xlarge past its 58 secondary-IP pods so the platform fits one node.
      # enableNetworkPolicy is the Watch It Burn delta: VPC-CNI enforces NetworkPolicy in-kernel,
      # which the egress beat (default-deny + allowlist) depends on. Without it, policies are inert
      # (found live on watch-it-burn-test). Pairs with the node group's maxPods (var.max_pods) below.
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
      # The module falls back to the cluster's subnet_ids when this is null (coalesce in node_groups.tf).
      subnet_ids   = var.node_subnet_ids
      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

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
      # hop_limit=1 (var.imds_hop_limit default) so pods cannot reach node IMDS. Pod Identity is unaffected:
      # it uses the container-creds endpoint 169.254.170.23, not IMDS (the kagent container held its Pod
      # Identity credential on watch-it-burn-attendee-001, built with these options, 2026-09-04, #203). The
      # agent namespace ALSO carries an explicit Admin-tier deny for 169.254.169.254
      # (policies/cluster-network-policies/), so the rule is readable in the lab and holds on attendee
      # clusters, which ship with no agent egress NetworkPolicy until the student applies Challenge 1.
      # The community/burn cluster deliberately sets var.imds_hop_limit=2 (fleet.sh, #113) so the IMDS
      # credential-theft challenge actually lands there; see the variable's definition above.
      metadata_options = {
        http_endpoint               = "enabled"
        http_tokens                 = "required"
        http_put_response_hop_limit = var.imds_hop_limit
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
      # NodeConfig (maxPods + fork-bomb pod-pids cap). See locals.nodeadm_part above.
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
# Confirmed live on watch-it-burn-attendee-001 2026-09-04 (#203): the kagent container carries
# AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/v1/credentials and the Pod Identity token file,
# and no key. This association is the agent's ONE cloud credential, and Bedrock invoke on the four models
# below is all it reaches; Challenge 8's probe (cloud-credential-probe.yaml in ~/challenges) shows the rest
# denied, and verify/test_agent_cloud_credential.py holds the lab's copy of this policy to the one here.
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
# fleet.sh pin_bedrock_profiles points each live Bedrock ModelConfig, and agentgateway's bedrock backend
# (#561), at this cluster's ARN from the output below. `consumer` keeps the agent's grant off the tutor's profile and the other way round.
resource "aws_bedrock_inference_profile" "agent" {
  for_each = local.bedrock_tiers

  name        = "${var.name}-${each.key}"
  description = "Watch It Burn agent on ${var.name}: ${each.value} tagged for cost allocation."
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
      # Two actions, not four. The Converse API is authorized by bedrock:InvokeModel and ConverseStream by
      # bedrock:InvokeModelWithResponseStream; IAM has no bedrock:Converse or bedrock:ConverseStream action,
      # and Access Analyzer's validate-policy failed the policy with ERROR INVALID_ACTION while it named
      # them (#203). The same holds for tutor_bedrock_invoke below.
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
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
# Scoped to ONE model family, where the agent's policy above covers the four the workshop binds. This
# is read-only inference only. A cluster-admin's reach is the union of every Pod
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

# Sonnet 4.6, the sonnet tier's model, since #882. It was us.anthropic.claude-sonnet-5, which has no Bedrock
# Marketplace agreement in accen-dev: IAM allowed the tutor's call and Bedrock refused it. Moving back to Sonnet 5
# means accepting its agreement in every fleet account first; fleet.sh preflight fails any account without it.
variable "tutor_model" {
  description = "Bedrock inference profile the workshop tutor uses. Its Marketplace agreement read AVAILABLE in accen-dev on 2026-11-05 (#882)."
  type        = string
  default     = "us.anthropic.claude-sonnet-4-6"
}

# The tutor's spend is tagged the same way as the agent's (#513). No tutor runs today (the web terminal's
# entrypoint removed it, #89), so nothing calls this yet; a replacement calls tutor_bedrock_profile_arn,
# not var.tutor_model, or its spend lands untagged again.
resource "aws_bedrock_inference_profile" "tutor" {
  name        = "${var.name}-tutor"
  description = "Watch It Burn workshop tutor on ${var.name}: ${var.tutor_model} tagged for cost allocation."
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

# --- lab-platform's harvest probe -------------------------------------------------------------------
#
# lab-platform's `labctl harvest` probes each seat's workshop apps through the seat's API server before it
# pools the seat (lab-platform#370), as the identity that read the seat's account. In the harvest's own (base)
# account that is the base credentials; in every other attendee account it is the role lab-platform creates
# there, lab-platform-operator (lab-platform docs/aws-accounts.md, "Creating the role"). Without this entry the
# role is refused with a 401 on every seat outside the base account, and each account had to be harvested with
# its own creator's key and the files joined with `labctl merge-pool` (#873).
#
# The entry carries the Kubernetes group lab-platform:learner-apps and no access policy, so all it can do is
# what that group's RBAC grants: get on the eight workshop apps' Service proxies, the read an attendee's check
# makes. That RBAC is gitops/learner-apps-access, synced on the attendee profile (#874); until it is on the seat
# the entry authenticates and is granted nothing.
#
# Seats only (role=attendee): the harvest pools nothing else, and lab-platform refuses the community and admin
# clusters at its own entries. An account may not hold the role (the harvest's base account needs none, and
# lab-platform makes it per account), and EKS refuses an entry for a principal that does not exist, so the entry
# is made where the role is found. A seat built before the role
# was created in its account gets the entry at its next apply.
locals {
  lab_platform_operator_role = "lab-platform-operator"
}

data "aws_iam_roles" "lab_platform_operator" {
  name_regex = "^${local.lab_platform_operator_role}$"
}

locals {
  admit_lab_platform_operator = var.role == "attendee" && length(data.aws_iam_roles.lab_platform_operator.names) == 1
}

data "aws_iam_role" "lab_platform_operator" {
  count = local.admit_lab_platform_operator ? 1 : 0
  name  = local.lab_platform_operator_role
}

# EKS binds an entry to its principal's unique id. lab-platform removes the role from an account once an event
# is over, and a role made again under the same name has a new id that the old entry no longer admits, while
# the ARN Terraform compares is unchanged. Tracking the id makes the next apply replace the entry.
resource "terraform_data" "lab_platform_operator_id" {
  count = local.admit_lab_platform_operator ? 1 : 0
  input = data.aws_iam_role.lab_platform_operator[0].unique_id
}

resource "aws_eks_access_entry" "lab_platform_operator" {
  count         = local.admit_lab_platform_operator ? 1 : 0
  cluster_name  = module.eks.cluster_name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.lab_platform_operator_role}"
  type          = "STANDARD"
  # The group lab-platform's harvest probe and an attendee's check share. No access policy is associated.
  kubernetes_groups = ["lab-platform:learner-apps"]
  lifecycle {
    replace_triggered_by = [terraform_data.lab_platform_operator_id[count.index]]
  }
}

output "attendee_iam_user" {
  value = aws_iam_user.attendee.name
}

# The ARN the harvest probe is admitted as on this seat, or "" where it is not (a roster cluster, the base
# account, or an account whose role lab-platform has not made yet).
output "lab_platform_operator_entry" {
  value = try(aws_eks_access_entry.lab_platform_operator[0].principal_arn, "")
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
