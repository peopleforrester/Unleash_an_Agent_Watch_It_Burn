# shellcheck shell=bash disable=SC2034  # sourced by fleet.sh; PROVIDER_* vars consumed there
# ABOUTME: AWS provider shim (PRD 35 §4.2). Supplies the provider-specific seam fleet.sh dispatches to:
# ABOUTME: the terraform network/cluster subpaths and how a cluster's kubeconfig is fetched.
# Terraform roots for this provider, relative to infra/terraform/ (the relocation put AWS under aws/).
PROVIDER_NETWORK_SUBDIR="aws/network"
PROVIDER_CLUSTER_SUBDIR="aws/cluster"
# provider_write_kubeconfig <cluster> <kubeconfig-file> <account-profile> [region]: fetch an isolated kubeconfig.
# EKS: aws eks update-kubeconfig. Never writes the shared ~/.kube/config. The region defaults to WIB_REGION; a
# standby in another region (backups.tsv, #643) passes its own.
provider_write_kubeconfig() {
    AWS_PROFILE="$3" aws eks update-kubeconfig --kubeconfig "$2" --name "$1" --region "${4:-${WIB_REGION}}" >/dev/null 2>&1
}
