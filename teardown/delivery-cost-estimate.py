#!/usr/bin/env python3
# ABOUTME: Estimates one delivery's AWS cost for a window from member-account data only (#392): resource hours from
# ABOUTME: CloudTrail and describe calls, Bedrock tokens from CloudWatch, priced from the AWS Price List API.
#
# Why this exists. teardown/cost-report.sh asks Cost Explorer for the tag-filtered spend, and that number is
# structurally 0.00 here: cost-allocation tags are activated on the PAYER account, the payer is the lab-account
# provider's Organization management account (457247706586, #202), and Michael's ruling on #392 (2026-11-01) is that
# nobody asks the provider for anything. So the delivery is costed from what each member account can read itself:
#
#   * EC2 instance hours by instance type, EKS cluster hours, EBS GiB-hours, NLB/ALB hours and NAT gateway hours,
#     from CloudTrail create/delete events (RunInstances/TerminateInstances, CreateCluster/DeleteCluster, ...) and,
#     for what is still running and was created before the CloudTrail lookback, from describe calls;
#   * NAT gateway data processed, from the AWS/NATGateway CloudWatch byte counters;
#   * Bedrock input and output tokens per model id, from the AWS/Bedrock CloudWatch metrics;
#   * every rate from the Price List API (pricing get-products), never a number written into this file.
#
# A resource counts when its own tags carry the delivery's tag filter (project=watch-it-burn, plus event=<event>
# with --event), or when it carries a cluster-ownership tag naming an EKS cluster that does. The second rule is
# what reaches the load balancers and CSI volumes, which the in-cluster controllers create without the fleet's
# default tags.
#
# What it prints is an ESTIMATE and says so on every report: each line item, what was left out, and each account's
# UNFILTERED Cost Explorer total for the same window beside it as an upper bound.
#
# Usage:
#   teardown/delivery-cost-estimate.py --start 2026-09-06 --end 2026-09-12 --region us-west-2 \
#       --event devopsdays-portland-2026 --profile accen-dev --profile aws1-student31 ...
# Every AWS call carries the given profile (AWS_PROFILE, per call) and region explicitly. Any call that fails ends
# the run: a partial estimate printed as if it were whole is the 0.00 problem again.
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

# Price List quotes storage per GB-month. 730 is the hours-per-month AWS uses on its own pricing pages.
HOURS_PER_MONTH = 730
# CloudTrail event history keeps 90 days. A window older than that cannot be estimated from it at all.
CLOUDTRAIL_RETENTION_DAYS = 90
# The pricing endpoint lives in us-east-1 whatever region is being priced.
PRICING_REGION = "us-east-1"
COST_EXPLORER_REGION = "us-east-1"

# The models the fleet calls, as Bedrock model ids without the cross-region routing prefix ("us."), and where the
# Price List carries each one. Amazon's own models are in AmazonBedrock; Anthropic's are sold as "Amazon Bedrock
# Edition" listings under AmazonBedrockFoundationModels. verify/test_delivery_cost_estimate.py fails when a model in
# the cluster root (bedrock_tiers, tutor_model) is missing here, so the table cannot fall behind the fleet.
BEDROCK_MODELS = {
    "amazon.nova-pro-v1:0": ("AmazonBedrock", "Nova Pro"),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ("AmazonBedrockFoundationModels", "Claude Haiku 4.5"),
    "anthropic.claude-sonnet-4-6": ("AmazonBedrockFoundationModels", "Claude Sonnet 4.6"),
    "anthropic.claude-opus-4-8": ("AmazonBedrockFoundationModels", "Claude Opus 4.8"),
    "anthropic.claude-sonnet-5": ("AmazonBedrockFoundationModels", "Claude Sonnet 5"),
}
GEO_PREFIXES = ("us.", "global.", "eu.", "apac.", "jp.", "au.", "ca.")
# Price variants that are not the on-demand, in-geography rate a "us." profile pays.
NOT_ON_DEMAND_REGIONAL = re.compile(r"global|batch|latency|cache|flex|priority|reserved", re.I)

# Tags by which an in-cluster controller (LB controller, EBS CSI, the node group) names the cluster it works for.
CLUSTER_VALUE_TAGS = ("elbv2.k8s.aws/cluster", "eks:cluster-name", "KubernetesCluster")
CLUSTER_KEY_TAG = re.compile(r"^kubernetes\.io/cluster/(.+)$")

# Not estimated, said on every report so the number is never read as the whole bill.
OMITTED = [
    "data transfer out and between AZs, and NLB/ALB capacity units (LCUs)",
    "T3 Unlimited CPU-credit surcharges and any gp3 IOPS or throughput above the free baseline",
    "public IPv4 address hours, EBS snapshots, CloudWatch, Logs, Secrets Manager, Route 53 and ECR",
    "partial hours are counted exactly, not rounded up, so hourly-billed items may run under by less than an hour each",
]


class AwsError(RuntimeError):
    pass


def aws(profile, region, *args):
    """One AWS CLI call as JSON, with the profile and region explicit on the call (CLAUDE.md, kube-context rules)."""
    env = dict(os.environ, AWS_PROFILE=profile)
    env.pop("AWS_DEFAULT_PROFILE", None)
    cmd = ["aws", *args, "--region", region, "--output", "json"]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise AwsError(f"[{profile}] aws {' '.join(args)} failed (exit {p.returncode}): {p.stderr.strip()}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def parse_time(v):
    """CloudTrail, the describe calls and the CLI write times in several ISO forms and, in RunInstances, epoch ms."""
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, dt.timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_key(obj, key):
    """First value of `key` (case-insensitive) anywhere in a CloudTrail element. EC2's newer APIs wrap their
    response (CreateNatGatewayResponse.natGateway.natGatewayId) and the older ones do not."""
    k = key.lower()
    if isinstance(obj, dict):
        for kk, vv in obj.items():
            if kk.lower() == k and not isinstance(vv, (dict, list)):
                return vv
        for vv in obj.values():
            r = find_key(vv, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for vv in obj:
            r = find_key(vv, key)
            if r is not None:
                return r
    return None


def tag_dict(raw):
    """Tags in any of the shapes AWS writes them: {k: v}, [{Key, Value}], [{key, value}], {items: [...]}."""
    if not raw:
        return {}
    if isinstance(raw, dict) and "items" in raw:
        raw = raw["items"]
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    out = {}
    for t in raw:
        k = t.get("Key", t.get("key"))
        if k is not None:
            out[str(k)] = str(t.get("Value", t.get("value", "")))
    return out


def spec_tags(request, resource_type):
    """Tags a create call asked for through a tagSpecificationSet, for one resource type."""
    out = {}
    for spec in (request or {}).get("tagSpecificationSet", {}).get("items", []):
        if spec.get("resourceType") == resource_type:
            out.update(tag_dict(spec.get("tags")))
    return out


def cluster_names(tags):
    names = {tags[k] for k in CLUSTER_VALUE_TAGS if tags.get(k)}
    for k in tags:
        m = CLUSTER_KEY_TAG.match(k)
        if m:
            names.add(m.group(1))
    return names


class Resource:
    def __init__(self, kind, rid, start, tags, **attrs):
        self.kind, self.rid, self.start, self.tags, self.attrs = kind, rid, start, tags, attrs
        self.end = None
        self.from_describe = False

    def hours_in(self, ws, we):
        s = max(self.start, ws)
        e = min(self.end or we, we)
        return max(0.0, (e - s).total_seconds() / 3600)


def pair_lifetimes(creates, deletes):
    """Each delete closes the latest open lifetime of its id. Names are reused (attendee-001 is built and torn down
    many times), so a cluster's lifetimes are paired in time order, not by name alone. A delete with no create in the
    lookback is a resource made before it: returned separately, because its tags were never seen."""
    by_id = {}
    for r in creates:
        by_id.setdefault(r.rid, []).append(r)
    for rs in by_id.values():
        rs.sort(key=lambda r: r.start)
    orphans = []
    for rid, when in sorted(deletes, key=lambda d: d[1]):
        open_ = [r for r in by_id.get(rid, []) if r.start <= when and r.end is None]
        if open_:
            open_[-1].end = when
        else:
            orphans.append((rid, when))
    return [r for rs in by_id.values() for r in rs], orphans


class Account:
    def __init__(self, profile, region, ws, we, lookup_start, lookup_end):
        self.profile, self.region = profile, region
        self.ws, self.we, self.ls, self.le = ws, we, lookup_start, lookup_end
        self.id = aws(profile, region, "sts", "get-caller-identity")["Account"]
        self.orphans = []

    def call(self, *args):
        return aws(self.profile, self.region, *args)

    def events(self, name):
        out = self.call("cloudtrail", "lookup-events",
                        "--lookup-attributes", f"AttributeKey=EventName,AttributeValue={name}",
                        "--start-time", iso(self.ls), "--end-time", iso(self.le))
        evs = []
        for e in out.get("Events", []):
            ct = json.loads(e["CloudTrailEvent"]) if isinstance(e.get("CloudTrailEvent"), str) else e.get("CloudTrailEvent", {})
            if ct.get("errorCode"):
                continue
            ct["_time"] = parse_time(ct.get("eventTime") or e["EventTime"])
            evs.append(ct)
        return evs

    def older_than_lookback(self, t):
        return t < self.ls

    # ---- EKS clusters ----
    def clusters(self):
        creates, deletes = [], []
        for e in self.events("CreateCluster"):
            if e.get("eventSource") != "eks.amazonaws.com":
                continue
            req = e.get("requestParameters") or {}
            name = req.get("name") or find_key(e.get("responseElements"), "name")
            creates.append(Resource("eks", name, e["_time"], tag_dict(req.get("tags"))))
        for e in self.events("DeleteCluster"):
            if e.get("eventSource") == "eks.amazonaws.com":
                deletes.append((find_key(e.get("requestParameters"), "name"), e["_time"]))
        live = []
        for name in self.call("eks", "list-clusters").get("clusters", []):
            c = self.call("eks", "describe-cluster", "--name", name)["cluster"]
            created = parse_time(c["createdAt"])
            if self.older_than_lookback(created):
                r = Resource("eks", name, created, tag_dict(c.get("tags")))
                r.from_describe = True
                live.append(r)
        rs, orphans = pair_lifetimes(creates, deletes)
        self.orphans += [("EKS cluster", *o) for o in orphans]
        return rs + live

    # ---- EC2 instances ----
    def instances(self, tag_filters):
        creates, deletes = [], []
        for e in self.events("RunInstances"):
            req = e.get("requestParameters") or {}
            asked = spec_tags(req, "instance")
            for it in ((e.get("responseElements") or {}).get("instancesSet") or {}).get("items", []):
                tags = dict(asked)
                tags.update(tag_dict(it.get("tagSet")))
                creates.append(Resource("ec2", it["instanceId"], e["_time"], tags, instance_type=it["instanceType"]))
        for e in self.events("TerminateInstances"):
            for it in ((e.get("requestParameters") or {}).get("instancesSet") or {}).get("items", []):
                deletes.append((it["instanceId"], e["_time"]))
        live = []
        out = self.call("ec2", "describe-instances", "--filters", *tag_filters,
                        "Name=instance-state-name,Values=pending,running,stopping,shutting-down")
        for res in out.get("Reservations", []):
            for i in res.get("Instances", []):
                launched = parse_time(i["LaunchTime"])
                if self.older_than_lookback(launched):
                    r = Resource("ec2", i["InstanceId"], launched, tag_dict(i.get("Tags")), instance_type=i["InstanceType"])
                    r.from_describe = True
                    live.append(r)
        rs, orphans = pair_lifetimes(creates, deletes)
        self.orphans += [("EC2 instance", *o) for o in orphans]
        return rs + live

    # ---- EBS volumes created on their own (CSI PVCs); node root disks are counted from the instances ----
    def volumes(self, tag_filters):
        creates, deletes = [], []
        for e in self.events("CreateVolume"):
            req, resp = e.get("requestParameters") or {}, e.get("responseElements") or {}
            tags = spec_tags(req, "volume")
            tags.update(tag_dict(resp.get("tagSet")))
            creates.append(Resource("ebs", resp["volumeId"], e["_time"], tags,
                                    size=int(resp.get("size") or req.get("size")),
                                    volume_type=resp.get("volumeType") or req.get("volumeType") or "gp2"))
        for e in self.events("DeleteVolume"):
            deletes.append(((e.get("requestParameters") or {})["volumeId"], e["_time"]))
        live = []
        for v in self.call("ec2", "describe-volumes", "--filters", *tag_filters).get("Volumes", []):
            created = parse_time(v["CreateTime"])
            root = any(a.get("DeleteOnTermination") and a.get("Device") in ("/dev/xvda", "/dev/sda1")
                       for a in v.get("Attachments", []))
            if self.older_than_lookback(created) and not root:
                r = Resource("ebs", v["VolumeId"], created, tag_dict(v.get("Tags")),
                             size=int(v["Size"]), volume_type=v["VolumeType"])
                r.from_describe = True
                live.append(r)
        rs, orphans = pair_lifetimes(creates, deletes)
        self.orphans += [("EBS volume", *o) for o in orphans]
        return rs + live

    # ---- load balancers (the LB controller's NLBs and ALBs) ----
    def load_balancers(self):
        creates, deletes = [], []
        for e in self.events("CreateLoadBalancer"):
            req, resp = e.get("requestParameters") or {}, e.get("responseElements") or {}
            lbs = resp.get("loadBalancers") or []
            if e.get("eventSource") != "elasticloadbalancing.amazonaws.com" or not lbs:
                continue  # a Classic ELB answers without loadBalancers; the fleet makes none
            lb = lbs[0]
            creates.append(Resource("elb", lb["loadBalancerArn"], e["_time"], tag_dict(req.get("tags")),
                                    lb_type=lb.get("type") or req.get("type") or "application"))
        for e in self.events("DeleteLoadBalancer"):
            arn = (e.get("requestParameters") or {}).get("loadBalancerArn")
            if arn:
                deletes.append((arn, e["_time"]))
        live = []
        old = [lb for lb in self.call("elbv2", "describe-load-balancers").get("LoadBalancers", [])
               if self.older_than_lookback(parse_time(lb["CreatedTime"]))]
        for i in range(0, len(old), 20):  # describe-tags takes at most 20 ARNs
            batch = old[i:i + 20]
            tags = {d["ResourceArn"]: tag_dict(d.get("Tags")) for d in self.call(
                "elbv2", "describe-tags", "--resource-arns", *[lb["LoadBalancerArn"] for lb in batch]).get("TagDescriptions", [])}
            for lb in batch:
                r = Resource("elb", lb["LoadBalancerArn"], parse_time(lb["CreatedTime"]),
                             tags.get(lb["LoadBalancerArn"], {}), lb_type=lb["Type"])
                r.from_describe = True
                live.append(r)
        rs, orphans = pair_lifetimes(creates, deletes)
        self.orphans += [("load balancer", *o) for o in orphans]
        return rs + live

    # ---- NAT gateways (one shared per lab VPC) ----
    def nat_gateways(self, tag_filters):
        creates, deletes = [], []
        for e in self.events("CreateNatGateway"):
            rid = find_key(e.get("responseElements"), "natGatewayId")
            if rid:
                creates.append(Resource("nat", rid, e["_time"], spec_tags(e.get("requestParameters"), "natgateway")))
        for e in self.events("DeleteNatGateway"):
            rid = find_key(e.get("requestParameters"), "natGatewayId")
            if rid:
                deletes.append((rid, e["_time"]))
        live = []
        for n in self.call("ec2", "describe-nat-gateways", "--filter", *tag_filters).get("NatGateways", []):
            created = parse_time(n["CreateTime"])
            if self.older_than_lookback(created):
                r = Resource("nat", n["NatGatewayId"], created, tag_dict(n.get("Tags")))
                if n.get("DeleteTime"):
                    r.end = parse_time(n["DeleteTime"])
                r.from_describe = True
                live.append(r)
        rs, orphans = pair_lifetimes(creates, deletes)
        self.orphans += [("NAT gateway", *o) for o in orphans]
        return rs + live

    def metric_sum(self, namespace, metric, dim_name, dim_value):
        out = self.call("cloudwatch", "get-metric-statistics", "--namespace", namespace, "--metric-name", metric,
                        "--dimensions", f"Name={dim_name},Value={dim_value}",
                        "--start-time", iso(self.ws), "--end-time", iso(self.we),
                        "--period", "86400", "--statistics", "Sum")
        return sum(float(d.get("Sum", 0)) for d in out.get("Datapoints", []))

    # ---- Bedrock application inference profiles (tagged per cluster since #513) ----
    def inference_profiles(self):
        out = []
        for e in self.events("CreateInferenceProfile"):
            req, resp = e.get("requestParameters") or {}, e.get("responseElements") or {}
            arn = resp.get("inferenceProfileArn")
            if arn:
                out.append(Resource("bedrock-profile", arn, e["_time"], tag_dict(req.get("tags")),
                                    source=find_key(req.get("modelSource"), "copyFrom") or ""))
        for p in self.call("bedrock", "list-inference-profiles", "--type-equals", "APPLICATION").get("inferenceProfileSummaries", []):
            created = parse_time(p["createdAt"])
            if self.older_than_lookback(created):
                tags = self.call("bedrock", "list-tags-for-resource", "--resource-arn", p["inferenceProfileArn"]).get("tags")
                models = [m.get("modelArn", "") for m in p.get("models", [])]
                r = Resource("bedrock-profile", p["inferenceProfileArn"], created, tag_dict(tags),
                             source=models[0] if models else "")
                r.from_describe = True
                out.append(r)
        return out

    def bedrock_dimensions(self):
        """ModelId values to read. list-metrics alone is not enough: it returns only metrics with data in the last
        two weeks, so a past delivery's model ids are added from the table above, in both routed and bare forms."""
        vals = set()
        for metric in ("InputTokenCount", "OutputTokenCount"):
            for m in self.call("cloudwatch", "list-metrics", "--namespace", "AWS/Bedrock", "--metric-name", metric).get("Metrics", []):
                for d in m.get("Dimensions", []):
                    if d.get("Name") == "ModelId":
                        vals.add(d["Value"])
        for mid in BEDROCK_MODELS:
            vals.update({mid, "us." + mid})
        return vals


def base_model(model_ref):
    """amazon.nova-pro-v1:0 from us.amazon.nova-pro-v1:0, or from a profile/model ARN ending in either."""
    s = model_ref.rsplit("/", 1)[-1]
    for p in GEO_PREFIXES:
        if s.startswith(p):
            return s[len(p):]
    return s


class Prices:
    """Rates from pricing get-products, one call per distinct query, cached for the run."""

    def __init__(self, profile, region):
        self.profile, self.region, self.cache = profile, region, {}

    def products(self, service, **filters):
        key = (service, tuple(sorted(filters.items())))
        if key not in self.cache:
            args = ["pricing", "get-products", "--service-code", service, "--filters"]
            args += [f"Type=TERM_MATCH,Field={k},Value={v}" for k, v in sorted(filters.items())]
            out = aws(self.profile, PRICING_REGION, *args)
            self.cache[key] = [json.loads(p) if isinstance(p, str) else p for p in out.get("PriceList", [])]
        return self.cache[key]

    @staticmethod
    def on_demand(item):
        dims = [d for term in item.get("terms", {}).get("OnDemand", {}).values()
                for d in term.get("priceDimensions", {}).values()]
        if len(dims) != 1:
            raise AwsError(f"price list sku {item['product'].get('sku')} has {len(dims)} on-demand price dimensions, expected 1")
        return float(dims[0]["pricePerUnit"]["USD"]), dims[0]["unit"], item["product"]["attributes"].get("usagetype", "")

    def one(self, what, service, usage_re=None, exclude=None, **filters):
        items = self.products(service, regionCode=self.region, **filters)
        if usage_re:
            items = [i for i in items if re.fullmatch(usage_re, i["product"]["attributes"].get("usagetype", ""))]
        if exclude:
            items = [i for i in items if not exclude.search(i["product"]["attributes"].get("usagetype", ""))]
        if len(items) != 1:
            found = sorted(i["product"]["attributes"].get("usagetype", "?") for i in items)
            raise AwsError(f"price list: {what} in {self.region} matched {len(items)} products, expected 1: {found}")
        return self.on_demand(items[0])

    def ec2_hour(self, instance_type):
        return self.one(f"EC2 {instance_type} Linux on-demand", "AmazonEC2",
                        usage_re=rf"(?:[A-Z0-9]+-)?BoxUsage:{re.escape(instance_type)}",
                        instanceType=instance_type, operatingSystem="Linux", tenancy="Shared",
                        preInstalledSw="NA", capacitystatus="Used", licenseModel="No License required")

    def ebs_gb_month(self, volume_type):
        return self.one(f"EBS {volume_type}", "AmazonEC2", productFamily="Storage", volumeApiName=volume_type)

    def eks_hour(self):
        return self.one("EKS standard cluster hour", "AmazonEKS", usage_re=r"(?:[A-Z0-9]+-)?AmazonEKS-Hours:perCluster",
                        operation="CreateOperation", locationType="AWS Region")

    def lb_hour(self, lb_type):
        family = {"network": "Load Balancer-Network", "application": "Load Balancer-Application"}[lb_type]
        return self.one(f"{family} hour", "AWSELB", usage_re=r"(?:[A-Z0-9]+-)?LoadBalancerUsage",
                        productFamily=family, locationType="AWS Region")

    def nat(self, what):
        return self.one(f"NAT gateway {what}", "AmazonEC2", usage_re=rf"(?:[A-Z0-9]+-)?NatGateway-{what}",
                        productFamily="NAT Gateway", operation="NatGateway")

    def bedrock_token(self, model_id, direction):
        service, name = BEDROCK_MODELS[model_id]
        price, unit, usage = self.one(f"Bedrock {name} {direction} tokens", service, exclude=NOT_ON_DEMAND_REGIONAL,
                                      model=name, feature="On-demand Inference", inferenceType=f"{direction} tokens")
        per = {"1K tokens": 1e3, "1M tokens": 1e6}.get(unit)
        if per is None:
            raise AwsError(f"price list: Bedrock {name} is priced per '{unit}', not per 1K or 1M tokens")
        return price / per, usage


class Matcher:
    def __init__(self, tag_key, tag_value, event):
        self.want = {tag_key: tag_value}
        if event:
            self.want["event"] = event

    def own(self, tags):
        return all(tags.get(k) == v for k, v in self.want.items())

    def disowned(self, tags):
        """The resource names a different value for a filter key, e.g. event=kubecon-na-2026 on a Portland run."""
        return any(k in tags and tags[k] != v for k, v in self.want.items())

    def describe_filters(self, flag="Name"):
        return [f"{flag}=tag:{k},Values={v}" for k, v in self.want.items()]


def estimate(args):
    ws = parse_time(args.start + "T00:00:00Z")
    we = parse_time(args.end + "T00:00:00Z")
    now = parse_time(args.as_of) if args.as_of else dt.datetime.now(dt.timezone.utc)
    retention_floor = now - dt.timedelta(days=CLOUDTRAIL_RETENTION_DAYS)
    if we <= retention_floor:
        raise AwsError(f"the window ends {iso(we)}, before CloudTrail's 90-day event history begins ({iso(retention_floor)}): "
                       "nothing in it can be read any more")
    lookup_start = max(ws - dt.timedelta(days=args.lookback_days), retention_floor)
    lookup_end = min(we, now)
    match = Matcher(args.tag_key, args.tag_value, args.event)
    prices = Prices(args.pricing_profile or args.profile[0], args.region)

    lines, notes, bounds = [], [], []

    def add(acct, item, qty, unit, rate, rate_unit):
        if qty > 0:
            lines.append((acct.profile, item, qty, unit, rate, rate_unit, qty * rate))

    for profile in args.profile:
        acct = Account(profile, args.region, ws, we, lookup_start, lookup_end)
        clusters = acct.clusters()
        fleet = [c for c in clusters if match.own(c.tags)]

        def ours(r):
            """Its own tags match, or it names a fleet cluster that was up when it was made. The lifetime matters
            because names are reused: attendee-001 rebuilt for KubeCon is not Portland's attendee-001."""
            if match.own(r.tags):
                return True
            if match.disowned(r.tags):
                return False
            names = cluster_names(r.tags)
            return any(c.rid in names and c.start <= r.start and (c.end is None or r.start <= c.end) for c in fleet)

        eks_hours = sum(c.hours_in(ws, we) for c in fleet)
        if eks_hours:
            rate, unit, _ = prices.eks_hour()
            add(acct, f"EKS cluster ({len([c for c in fleet if c.hours_in(ws, we)])} lifetimes)", eks_hours, "cluster-h", rate, unit)

        by_type, root_gib_h = {}, 0.0
        for i in acct.instances(match.describe_filters()):
            if not ours(i):
                continue
            h = i.hours_in(ws, we)
            by_type[i.attrs["instance_type"]] = by_type.get(i.attrs["instance_type"], 0.0) + h
            root_gib_h += h * args.root_volume_gib
        for itype, h in sorted(by_type.items()):
            rate, unit, _ = prices.ec2_hour(itype)
            add(acct, f"EC2 {itype}", h, "instance-h", rate, unit)

        gib_h = {}
        if root_gib_h:
            gib_h[args.root_volume_type] = root_gib_h
        for v in acct.volumes(match.describe_filters()):
            if ours(v):
                gib_h[v.attrs["volume_type"]] = gib_h.get(v.attrs["volume_type"], 0.0) + v.hours_in(ws, we) * v.attrs["size"]
        for vtype, q in sorted(gib_h.items()):
            rate, unit, _ = prices.ebs_gb_month(vtype)
            add(acct, f"EBS {vtype}" + (" (incl. node root disks)" if vtype == args.root_volume_type and root_gib_h else ""),
                q, "GiB-h", rate / HOURS_PER_MONTH, f"{unit}/{HOURS_PER_MONTH}h")

        lb_hours = {}
        for lb in acct.load_balancers():
            if ours(lb) and lb.attrs["lb_type"] in ("network", "application"):
                lb_hours[lb.attrs["lb_type"]] = lb_hours.get(lb.attrs["lb_type"], 0.0) + lb.hours_in(ws, we)
        for lbt, h in sorted(lb_hours.items()):
            rate, unit, _ = prices.lb_hour(lbt)
            add(acct, {"network": "NLB", "application": "ALB"}[lbt], h, "lb-h", rate, unit)

        nat_h, nat_gb = 0.0, 0.0
        for n in acct.nat_gateways(match.describe_filters()):
            if not ours(n):
                continue
            h = n.hours_in(ws, we)
            if h:
                nat_h += h
                processed = sum(acct.metric_sum("AWS/NATGateway", m, "NatGatewayId", n.rid)
                                for m in ("BytesInFromSource", "BytesInFromDestination"))
                nat_gb += processed / 1e9
        if nat_h:
            rate, unit, _ = prices.nat("Hours")
            add(acct, "NAT gateway", nat_h, "nat-h", rate, unit)
        if nat_gb:
            rate, unit, _ = prices.nat("Bytes")
            add(acct, "NAT gateway data processed", nat_gb, "GB", rate, unit)

        # Bedrock. A tagged application profile's tokens are the fleet's; a system model id's are the whole
        # account's, which before #513 (2026-10-25) is every call the fleet made, and on accen-dev includes Packt.
        profiles = {p.rid: p for p in acct.inference_profiles() if ours(p)}
        profile_ids = {arn.rsplit("/", 1)[-1]: arn for arn in profiles}
        untagged = 0.0
        # Both forms of each tagged profile: the ARN and its trailing id. Only one of them carries data.
        dims = acct.bedrock_dimensions() | set(profiles) | set(profile_ids)
        for dim in sorted(dims):
            arn = dim if dim in profiles else profile_ids.get(dim)
            if "application-inference-profile" in dim and not arn:
                continue  # another tenant's, or a profile outside the filter
            model = base_model(profiles[arn].attrs["source"]) if arn else base_model(dim)
            for direction, metric in (("Input", "InputTokenCount"), ("Output", "OutputTokenCount")):
                tokens = acct.metric_sum("AWS/Bedrock", metric, "ModelId", dim)
                if not tokens:
                    continue
                if model not in BEDROCK_MODELS:
                    notes.append(f"{profile}: {tokens:,.0f} Bedrock {direction.lower()} tokens on {dim}, a model this "
                                 "script has no price for; not counted")
                    continue
                rate, _ = prices.bedrock_token(model, direction)
                if arn:
                    add(acct, f"Bedrock {BEDROCK_MODELS[model][1]} {direction.lower()} (tagged profile)",
                        tokens, "tokens", rate, "token")
                else:
                    untagged += tokens * rate
                    notes.append(f"{profile}: {tokens:,.0f} {direction.lower()} tokens on {dim} = "
                                 f"{tokens * rate:,.2f} USD, account-wide and untagged (not in the estimate)")
        for kind, rid, when in acct.orphans:
            notes.append(f"{profile}: {kind} {rid} was deleted {iso(when)} but made before the CloudTrail lookback, "
                         "so its tags and start are unknown; not counted (raise --lookback-days)")

        ce = aws(profile, COST_EXPLORER_REGION, "ce", "get-cost-and-usage",
                 "--time-period", f"Start={args.start},End={args.end}", "--granularity", "MONTHLY",
                 "--metrics", "UnblendedCost")
        bound = sum(float(r["Total"]["UnblendedCost"]["Amount"]) for r in ce.get("ResultsByTime", []))
        bounds.append((profile, acct.id, bound, untagged))

    return dict(ws=ws, we=we, lookup_start=lookup_start, retention_floor=retention_floor,
                lines=lines, notes=notes, bounds=bounds, match=match)


def render(args, r):
    out = []
    w = out.append
    w("=" * 100)
    w("  ESTIMATE, NOT A BILL: one delivery's AWS cost from member-account data only (#392)")
    w(f"  Window: {args.start} (incl) .. {args.end} (excl), UTC, region {args.region}")
    w("  Filter: " + ", ".join(f"{k}={v}" for k, v in r["match"].want.items())
      + " (or a cluster-ownership tag naming a cluster that carries it)")
    w(f"  CloudTrail read from {iso(r['lookup_start'])}; its event history for this window ends {iso(r['ws'] + dt.timedelta(days=CLOUDTRAIL_RETENTION_DAYS))}")
    w("  Rates: AWS Price List API, on-demand, " + args.region)
    w("=" * 100)
    w(f"  {'account':<16} {'line item':<46} {'quantity':>14} {'unit':<10} {'rate USD':>12}  {'USD':>10}")
    total = 0.0
    for profile, item, qty, unit, rate, rate_unit, usd in r["lines"]:
        w(f"  {profile:<16} {item:<46} {qty:>14,.2f} {unit:<10} {rate:>12.6g}  {usd:>10,.2f}")
        total += usd
    if not r["lines"]:
        w("  (no tagged resource ran in this window)")
    w("-" * 100)
    w(f"  ESTIMATED TOTAL, tagged resources:{total:>64,.2f} USD")
    untagged = sum(b[3] for b in r["bounds"])
    if untagged:
        w(f"  ... plus untagged Bedrock on the same accounts:{untagged:>51,.2f} USD")
        w(f"  ESTIMATE IF THAT BEDROCK IS ALL THE FLEET'S:{total + untagged:>54,.2f} USD")
    w("")
    w("  Upper bound, each account's UNFILTERED Cost Explorer total for the same window (whole account,")
    w("  any co-tenant included, never the workshop's cost):")
    for profile, acct_id, bound, _ in r["bounds"]:
        w(f"    {profile:<16} {acct_id:<14} {bound:>12,.2f} USD")
    w(f"    {'all accounts':<31} {sum(b[2] for b in r['bounds']):>12,.2f} USD")
    w("")
    w("  Not in the estimate:")
    for o in OMITTED:
        w(f"    - {o}")
    for n in r["notes"]:
        w(f"    - {n}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimate one delivery's AWS cost from member-account data only (#392). "
                                 "Prints an estimate, never a bill, beside each account's unfiltered Cost Explorer total.")
    ap.add_argument("--start", required=True, help="window start, YYYY-MM-DD, inclusive (UTC)")
    ap.add_argument("--end", required=True, help="window end, YYYY-MM-DD, exclusive (UTC), the Cost Explorer convention")
    ap.add_argument("--region", required=True, help="the fleet's region, e.g. us-west-2")
    ap.add_argument("--profile", action="append", required=True,
                    help="an AWS profile of a member account the fleet ran in; repeat for each account")
    ap.add_argument("--event", help="also require event=<value>, to cost one delivery (e.g. devopsdays-portland-2026)")
    ap.add_argument("--tag-key", default="project")
    ap.add_argument("--tag-value", default="watch-it-burn")
    ap.add_argument("--lookback-days", type=int, default=30,
                    help="how far before --start to read CloudTrail for resources made earlier (default 30)")
    ap.add_argument("--root-volume-gib", type=int, default=100,
                    help="each node's root disk, node_disk_size in infra/terraform/aws/cluster (default 100)")
    ap.add_argument("--root-volume-type", default="gp3")
    ap.add_argument("--pricing-profile", help="profile for the Price List API (default: the first --profile)")
    ap.add_argument("--as-of", help="the time CloudTrail's 90-day history is counted back from (default: now)")
    args = ap.parse_args(argv)
    for d in (args.start, args.end):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            ap.error(f"dates must be YYYY-MM-DD, got {d}")
    if args.end <= args.start:
        ap.error("--end must be after --start")
    try:
        sys.stdout.write(render(args, estimate(args)))
    except AwsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
