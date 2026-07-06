# shellcheck shell=bash disable=SC2034  # sourced by fleet.sh; PROVIDER_* vars consumed there
# ABOUTME: local (k3d/kind) provider shim — M1 STUB. Real target lands in PRD 35 M8.
PROVIDER_NETWORK_SUBDIR=""   # local has no terraform network root
PROVIDER_CLUSTER_SUBDIR=""
provider_write_kubeconfig() { log "provider 'local' not implemented yet (M1 stub); see PRD 35 M8"; return 1; }
