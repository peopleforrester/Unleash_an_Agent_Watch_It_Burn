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

# The instructor's fleet view (#150): who is in the lab, how far each attendee got, where they asked for help,
# and what the guardrails caught, across every cluster at once. Apply it to the INSTRUCTOR org (the one attendee
# clusters dual-ship to, #242), with that org's DD_API_KEY and DD_APP_KEY. In a student's own org it renders
# empty by design: the lab markers it reads are only shipped to the instructor org.
resource "datadog_dashboard_json" "fleet_analytics" {
  dashboard = file("${path.module}/fleet-analytics.json")
}
