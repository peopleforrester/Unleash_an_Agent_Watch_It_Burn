<!-- ABOUTME: The single tagging + naming convention for Watch It Burn AWS resources. Exists because the -->
<!-- ABOUTME: the primary account is shared with a separate project; this keeps our resources distinct. -->

# Tagging and naming convention (collision avoidance)

The primary AWS account is **shared with a separate project** that runs its own clusters. We never share resources with it. Every
resource we create is labeled so it is unambiguously ours, and every scoping or
teardown action filters on that label so it can only ever touch our resources.

## The one rule

**Every Watch It Burn resource carries the tag `project=watch-it-burn`, and every
cluster name starts with `watch-it-burn-`.**

That tag is the bundling key. AWS has no Azure-style resource group; the AWS
equivalent is a **tag-based Resource Group** (a saved tag query). So the tag is
both the label and the grouping mechanism.

## Standard tags

| Key | Value | On |
|---|---|---|
| `project` | `watch-it-burn` | every resource (the discriminator) |
| `event` | `ai-engineer-worldsfair-2026` | clusters, buckets, secrets |
| `role` | `attendee` / `test` / `c1-1` / `c2-3` / `c3-inst-1` / ... | clusters + nodegroups |
| `attendee` | the attendee id | attendee clusters only |
| `component` | `exfil-game-hoop` / `exfil-game-trophy` / ... | non-cluster AWS resources |

## Naming

All EKS cluster names start with `watch-it-burn-` (independent clusters; no hub):

- `watch-it-burn-attendee-<ATTENDEE_ID>` (one independent cluster per attendee, take-home)
- `watch-it-burn-test` (validation cluster)
- `watch-it-burn-<CLUSTER_ID>` (burn/instructor/presenter: `c1-1`, `c2-3`, `c3-inst-1`, ...)

S3 buckets: `watch-it-burn-<purpose>` (e.g. `watch-it-burn-exfil-hoop`).
Secrets Manager: `watch-it-burn/<purpose>` (e.g. `watch-it-burn/exfil-game-trophy`).

## Where the tags are applied

- **EKS clusters + all AWS resources** - Terraform `provider "aws" { default_tags { ... } }` in
  `infra/terraform/aws/network/main.tf` and `infra/terraform/aws/cluster/main.tf`. default_tags applies
  `project=watch-it-burn` to every resource the provider creates (VPC, cluster, node group, IRSA /
  Pod Identity roles, EBS), so the whole stack inherits it. The per-attendee cluster also gets
  `attendee=<name>`. (Provisioning is Terraform, not eksctl.)
- **Node groups / EC2 / EBS** - inherited from the provider default_tags above.
- **S3 buckets** - `aws s3api put-bucket-tagging` in `games/eso-s3-exfil/s3-hoop-setup.sh`.
- **Secrets Manager** - `--tags` on `create-secret` in `games/eso-s3-exfil/plant-trophy.sh`.
- **Load balancers** (when a demo Service is exposed as `type: LoadBalancer` at
  provision time) - the AWS Load Balancer Controller does NOT inherit cluster tags,
  so the Service must carry:
  ```yaml
  metadata:
    annotations:
      service.beta.kubernetes.io/aws-load-balancer-additional-resource-tags: "project=watch-it-burn,event=ai-engineer-worldsfair-2026,role=<role>"
  ```
  All demo Services are `ClusterIP` today; add this annotation when exposure is wired
  in the provisioning project (see the DNS linkage below).

## Collision-safety rule for scripts

Every scoping or teardown action filters on our name prefix or our tag. Never run an
account-wide delete. Examples already in the repo:

- teardown: prefix-scoped to `watch-it-burn-*` (teardown/teardown.sh refuses any other prefix).
- exfil game: operates only on `watch-it-burn-exfil-hoop` / `watch-it-burn/exfil-game-trophy`.

## Verify what is ours (read-only)

```bash
# Every resource tagged ours, account-wide:
aws resourcegroupstaggingapi get-resources --profile accen-dev --region us-west-2 \
  --tag-filters Key=project,Values=watch-it-burn \
  --query 'ResourceTagMappingList[].ResourceARN' --output text

# Optional: a saved Resource Group bundling them in the console.
aws resource-groups create-group --profile accen-dev --region us-west-2 \
  --name watch-it-burn \
  --resource-query '{"Type":"TAG_FILTERS_1_0","Query":"{\"ResourceTypeFilters\":[\"AWS::AllSupported\"],\"TagFilters\":[{\"Key\":\"project\",\"Values\":[\"watch-it-burn\"]}]}"}'
```

## Public-URL linkage (agenticburn.com) - provisioning TODO

The provisioning process will attach public URLs to each cluster:

1. Provision a `watch-it-burn-*` cluster (tagged per above).
2. Expose the demo Service as `type: LoadBalancer` with the LB tag annotation above.
3. Read the LB hostname: `kubectl --context <ctx> -n <ns> get svc <svc> -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'`.
4. Point a subdomain at it via the existing tool:
   `python3 infra/dns/set-demo-dns.py --apply burn=<lb-host> wall=<lb-host> haiku=<lb-host> ...`
   (CNAME `*.agenticburn.com` -> the AWS ELB hostname; the tool merges so the apex/parking
   records survive. Mutation needs Michael's go per the namecheap-api rule.)

The cluster -> LB-hostname -> `*.agenticburn.com` mapping is the linkage; the
automation that runs steps 3-4 per cluster is the deferred provisioning work.
See `infra/dns/README.md`.
