# ABOUTME: The providers OpenTofu installs in the plan-policy check, pinned so .terraform.lock.hcl beside this file
# ABOUTME: records their registry.opentofu.org hashes: the lock vouches for each zip the host artifact cache mirrors (#1131).
#
# Never applied and never planned. test_plan_policy_e2e.py runs tofu on fixtures/ and, through plan-fleet.py, on
# infra/terraform/aws/network and aws/cluster. tofu resolves `hashicorp/<type>` on registry.opentofu.org, whose
# packages are OpenTofu's own builds (github.com/opentofu/terraform-provider-<type>), so their SHA-256s are none of
# the zh: hashes the registry.terraform.io locks record and those locks cannot vouch for them. This lock does:
# verify/tf_plugin_cache.py fills the mirror's registry.opentofu.org half from it, and the CLI config gives that host
# no `direct` source, so a provider missing here fails tofu init by name instead of being downloaded.
#
# Each version is the newest a committed infra/ lock pins for registry.terraform.io, so tofu plans with the providers
# terraform does. When a fleet root needs a new provider or version, change it here and regenerate the lock from this
# directory (a copy outside the worktree keeps .terraform out of the checkout):
#   tofu providers lock -platform=linux_amd64
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
    cloudinit = {
      source  = "hashicorp/cloudinit"
      version = "2.4.1"
    }
    null = {
      source  = "hashicorp/null"
      version = "3.3.2"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.14.2"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "4.4.2"
    }
  }
}
