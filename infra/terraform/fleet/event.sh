# shellcheck shell=bash disable=SC2034  # sourced; WIB_EVENT is consumed by the sourcing script
# ABOUTME: The fleet's `event` cost-allocation tag, set in this one place. fleet.sh, preflight.sh and the
# ABOUTME: lab-VPC teardown scripts source it and pass it to both Terraform roots as -var event=<value>.
#
# Spend is split per event by this tag (teardown/cost-report.sh, the payer account's cost-allocation
# tags), so a fleet that carries the last event's value bills into the last event's bucket. It used to be
# a literal in each root's default_tags, which is how clusters built for KubeCon NA were still tagged
# with the Portland value a month after Portland (#494). Neither root has a default for `event`: an apply
# that does not pass it fails, rather than quietly tagging with whatever value a root last carried.
#
# For the next event, change this value. WIB_EVENT in the environment overrides it for one run.
# KubeCon NA 2026: Michael's answer on #454 (2026-10-23).
WIB_EVENT="${WIB_EVENT:-kubecon-na-2026}"
