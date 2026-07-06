# shellcheck shell=bash disable=SC2034  # sourced by fleet.sh; PROVIDER_* vars consumed there
# ABOUTME: Azure provider shim — M1 STUB. Terraform roots + kubeconfig land in PRD 35 M2/M3.
PROVIDER_NETWORK_SUBDIR="azure/network"
PROVIDER_CLUSTER_SUBDIR="azure/cluster"
provider_write_kubeconfig() { log "provider 'azure' not implemented yet (M1 stub); see PRD 35 M2/M3"; return 1; }
