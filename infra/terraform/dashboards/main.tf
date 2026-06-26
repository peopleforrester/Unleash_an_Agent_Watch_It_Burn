# ABOUTME: Terraform module for Datadog dashboards as code.
# ABOUTME: Scaffolded in PRD #33; custom dashboards added at dress rehearsal.
#
# Standalone module, same convention as the sibling cluster/ and lab-vpc/ modules: its own
# terraform {} block, no root-module wiring. The three OOTB dashboards (cert-manager, Kyverno,
# ArgoCD) auto-install via the Datadog Agent checks and are NOT managed here (PRD #33 locked
# decision: Datadog manages Agent-installed dashboards automatically). This module exists only for
# the four custom/story dashboards deferred to dress rehearsal.

terraform {
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = "~> 3.0"
    }
  }
}

provider "datadog" {
  # api_key and app_key read from DD_API_KEY and DD_APP_KEY env vars
}

# Placeholder: uncomment and populate at dress rehearsal for each custom dashboard.
# Each dashboard JSON file goes alongside this module (e.g., ./wasted-tokens.json). The four
# custom/story dashboards planned (PRD #33): Wasted Tokens Over Time, Model Tier Cost Race,
# Tool Call Heatmap, Guardrail Toggle Timeline. They cannot be built until a full workshop run
# produces live LLM-agent telemetry to validate the queries against.
#
# resource "datadog_dashboard_json" "wasted_tokens" {
#   dashboard = file("${path.module}/wasted-tokens.json")
# }
