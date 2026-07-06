# shellcheck shell=bash disable=SC2034  # sourced by fleet.sh; PROVIDER_* vars consumed there
# ABOUTME: Gcp provider shim — M1 STUB. Terraform roots + kubeconfig land in PRD 35 M2/M3.
PROVIDER_NETWORK_SUBDIR="gcp/network"
PROVIDER_CLUSTER_SUBDIR="gcp/cluster"
provider_write_kubeconfig() { log "provider 'gcp' not implemented yet (M1 stub); see PRD 35 M2/M3"; return 1; }
