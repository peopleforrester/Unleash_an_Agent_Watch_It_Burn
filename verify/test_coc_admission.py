# ABOUTME: Offline check of the code-of-conduct admission policy on names and labels in `agent` (#1278): its pattern is
# ABOUTME: the floor's RE2 form, every name the stage creates passes it, and no switch, reset or stage identity lifts it.
"""No cluster, no network, standard library and PyYAML.

gitops/namespaces/code-of-conduct-names.yaml is a native ValidatingAdmissionPolicy and its binding. It refuses a create
or update in the `agent` namespace whose name or labels match the floor the spike chose (#1267,
docs/research/2026-11-09-coc-floor), outside Kyverno so that guardrails-k8s-off leaves it on. This holds:

1. The shape: the policy and binding, Deny, failurePolicy Fail, CREATE and UPDATE of every namespaced kind, bound to
   `agent` alone, scoped to the room's and people's writes, in the namespaces Application that every profile lists.
2. The pattern is floor.name_pattern() exactly (#1316): on any text a name and labels can make it refuses what
   floor.portable_pattern(), the collector's form, refuses, which this checks on every term's spellings and on
   random name text; and the message and expressions name no term.
3. The text CEL matches is what this test builds (the expressions are held literally), and on it every Joker slug of
   the 768 witch names, built as deploy_app builds it, every stage image's Deployment the agent prompt names, and every
   object under gitops/ passes, while every term the list holds, in a name or a label, is refused. The longest of
   those texts costs CEL's matches() well inside its 1,000,000 a call, so none is refused for its length.
4. guardrails-k8s-off, guardrails-ai-off and the reset scripts leave it in place: neither terminal entrypoint nor fleet.sh names
   an admission policy, the files guardrails-k8s-off applies and deletes hold none, its Kyverno step patches Kyverno's
   ValidatingPolicy alone, and no Role or ClusterRole in the stage's bundles grants a write on admission policies.
"""
from __future__ import annotations

import codecs
import importlib.util
import math
import pathlib
import random
import re
import sys
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
sys.path.insert(0, str(SPIKE))

import corpus  # noqa: E402
import floor  # noqa: E402

POLICY_FILE = REPO / "gitops/namespaces/code-of-conduct-names.yaml"
NAME = "code-of-conduct-names"
AI = REPO / "gitops/ai-layer"
ENTRYPOINTS = (AI / "web-terminal/entrypoint.sh", REPO / "images/web-terminal/entrypoint.sh")
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
RESOURCES = AI / "resources.yaml"
AGENT_YAML = REPO / "gitops/workshop-agent/agent.yaml"
# The CEL the policy evaluates, held literally, so that cel_text() below stays the text the cluster matches.
LABEL_SETS = ("[object.metadata.?labels.orValue({}), object.?spec.?template.?metadata.?labels.orValue({}), "
              "object.?spec.?jobTemplate.?metadata.?labels.orValue({}), "
              "object.?spec.?jobTemplate.?spec.?template.?metadata.?labels.orValue({})]")
TEXT = ("([object.metadata.?name.orValue('')] + "
        "variables.labelSets.map(m, m.map(k, k + '=' + string(m[k])).join('/'))).join('/')")
VALIDATION = "!variables.text.matches(variables.floor)"
WHO = ("!request.userInfo.username.startsWith('system:') || "
       "request.userInfo.username.startsWith('system:serviceaccount:agent:')")
WRITE_VERBS = {"create", "update", "patch", "delete", "deletecollection", "*"}
# What makes a manifest name an admission policy, in a script or a file guardrails-k8s-off applies.
ADMISSION_WORDS = re.compile(r"admissionregistration|validatingadmissionpolic|code-of-conduct-names|"
                             r"validatingwebhookconfiguration", re.IGNORECASE)

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def need(path: pathlib.Path, literal: str) -> str:
    """The file's text, after checking it still holds the anchor this test cuts on (Tests own their inputs, point 2)."""
    text = path.read_text(encoding="utf-8")
    if literal not in text:
        print(f"  FAIL  {path.relative_to(REPO)} no longer holds {literal!r}, which this test reads it by")
        sys.exit(1)
    return text


def labels_of(obj: dict, *path: str) -> dict:
    node = obj
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def cel_text(obj: dict) -> str:
    """variables.text: the name, then each label set's key=value pairs joined with '/', all joined with '/'."""
    sets = [labels_of(obj, "metadata", "labels"), labels_of(obj, "spec", "template", "metadata", "labels"),
            labels_of(obj, "spec", "jobTemplate", "metadata", "labels"),
            labels_of(obj, "spec", "jobTemplate", "spec", "template", "metadata", "labels")]
    name = (obj.get("metadata") or {}).get("name") or ""
    return "/".join([str(name)] + ["/".join(f"{k}={v}" for k, v in s.items()) for s in sets])


def one_line(expr: str) -> str:
    return " ".join(expr.split())


print("== 1. the policy and its binding ==")
docs = [d for d in yaml.safe_load_all(POLICY_FILE.read_text(encoding="utf-8")) if d]
vap = next((d for d in docs if d.get("kind") == "ValidatingAdmissionPolicy"), {})
vapb = next((d for d in docs if d.get("kind") == "ValidatingAdmissionPolicyBinding"), {})
check([d.get("kind") for d in docs] == ["ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"]
      and all(d.get("apiVersion") == "admissionregistration.k8s.io/v1" for d in docs)
      and vap["metadata"]["name"] == NAME and vapb["metadata"]["name"] == NAME,
      f"{POLICY_FILE.relative_to(REPO)} holds the policy {NAME} and its binding, admissionregistration.k8s.io/v1")
spec = vap.get("spec") or {}
check(spec.get("failurePolicy") == "Fail", "failurePolicy Fail: an evaluation that errors refuses the write")
check((spec.get("matchConstraints") or {}).get("resourceRules") == [
    {"apiGroups": ["*"], "apiVersions": ["*"], "operations": ["CREATE", "UPDATE"], "resources": ["*"],
     "scope": "Namespaced"}],
    "it matches CREATE and UPDATE of every namespaced kind (deploy_app applies any single namespaced resource)")
conds = spec.get("matchConditions") or []
check(len(conds) == 1 and one_line(conds[0].get("expression", "")) == WHO,
      "it reads every write but the cluster's own system identities', and every write from a service account in agent")
variables = {v["name"]: v["expression"] for v in spec.get("variables") or []}
check(list(variables) == ["floor", "labelSets", "text"] and one_line(variables["labelSets"]) == LABEL_SETS
      and one_line(variables["text"]) == TEXT,
      "the text matched is the name and the labels of the object and of its pod template, as cel_text() builds it")
vals = spec.get("validations") or []
check(len(vals) == 1 and vals[0].get("expression") == VALIDATION and vals[0].get("reason") == "Forbidden",
      f"one validation, {VALIDATION}, refused as Forbidden")
bspec = vapb.get("spec") or {}
check(bspec.get("policyName") == NAME and bspec.get("validationActions") == ["Deny"],
      "the binding names the policy and denies (not Audit or Warn)")
check(bspec.get("matchResources") == {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "agent"}}},
      "the binding selects the agent namespace alone")

app = yaml.safe_load((REPO / "gitops/bootstrap/apps/namespaces.yaml").read_text(encoding="utf-8"))
check(app["spec"]["source"]["path"] == "gitops/namespaces" and app["spec"]["source"].get("directory") is None
      and app["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True}
      and not app["spec"].get("ignoreDifferences"),
      "the namespaces Application syncs every file in gitops/namespaces with prune and selfHeal and ignores no field")
values = sorted((REPO / "gitops/bootstrap").glob("values-*.yaml"))
missing = [v.name for v in values if "namespaces" not in (yaml.safe_load(v.read_text(encoding="utf-8")) or {}).get(
    "apps", [])]
check(len(values) >= 6 and not missing, f"every profile ({len(values)}) lists the namespaces Application "
                                        f"(missing from: {missing})")

print("== 2. the pattern is the floor's RE2 form, and nothing it says names a term ==")
expr = variables.get("floor", "")
pattern = floor.name_pattern()
check(expr == f"r'{pattern}'" and "'" not in pattern,
      f"variables.floor is floor.name_pattern() as one CEL raw string ({len(pattern)} characters)")
# re.ASCII has Python's (?i) fold ASCII letters alone, as RE2's does in CEL's matches().
P = re.compile(pattern, re.ASCII)
# A name or a label holds letters, digits, ".", "-" and "_"; the text joins them with "/" and "=". On such text the
# name form must refuse exactly what the collector's form refuses. Each term is tried as a name would spell it (its
# spaces as each separator, spelt out, upper case, plural, inside other words), and so is random name text, seeded.
PORTABLE = re.compile(floor.portable_pattern(), re.ASCII)
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_/="
_rnd = random.Random(1316)
names = ["".join(_rnd.choice(ALPHABET) for _ in range(_rnd.randint(1, 48))) for _ in range(20000)]
for term in corpus.terms("proposed"):
    word = floor.fold(term)[0]
    if all(c in ALPHABET or c == " " for c in word):
        for sep in "-._":
            slug = word.replace(" ", sep)
            names += [slug, f"joker-{slug}", f"app={slug}s", sep.join(word.replace(" ", "")), slug.upper(),
                      f"x{slug}", f"{slug}y", f"a/{slug}/b"]
differ = [codecs.encode(n, "rot13") for n in names if bool(P.search(n)) != bool(PORTABLE.search(n))]
check(not differ, f"on {len(names)} texts a name and labels can make, floor.name_pattern() refuses exactly what "
                  f"floor.portable_pattern() refuses (differ, ROT13: {differ[:5]})")
folded = floor.Floor("proposed")
said = [vals[0].get("message", "") if vals else "", variables.get("labelSets", ""), variables.get("text", ""),
        VALIDATION, WHO]
check(bool(said[0]) and not any(P.search(s) or folded.spans(s) for s in said),
      "the refusal message and every expression but the pattern itself name no term, folded or not")

print("== 3. every name the stage creates passes; every term is refused ==")
# deploy_app's own code builds the Jokers and stamps the labels (the import pattern verify/test_deploy_app_*.py use).


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec_ = importlib.util.spec_from_file_location("workshop_mcp_coc_admission", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(server)


def deployment(name: str, image: str) -> dict:
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "namespace": "agent",
                                                                        "labels": {"app": name}},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}},
                                  "spec": {"containers": [{"name": name, "image": image}]}}}}


slugs = [n for n in corpus._witch_names() if n.startswith("joker-")]
jokers = [server._plain_room_joker(deployment(s, "registry.burritobot.co/burritobot/maintenance-shell:x"), s)
          for s in slugs]
bad = [j["metadata"]["name"] for j in jokers if P.search(cel_text(j))]
check(len(slugs) == 768 and all(j and j["spec"]["template"]["metadata"]["labels"].get(server.ROOM_JOKER_LABEL)
                                for j in jokers) and not bad,
      f"all {len(slugs)} Joker slugs pass, each built by deploy_app's _plain_room_joker with its stamped labels "
      f"(refused: {bad[:5]})")

prompt = need(AGENT_YAML, "use exactly its image below")
games = re.findall(r"^\s+- ([A-Za-z0-9][A-Za-z0-9 ]*): (\S+@sha256:[0-9a-f]{64})$", prompt, re.M)
stage = []
for game, image in games:
    repo_name = image.split("@")[0].rsplit("/", 1)[-1].split(":")[0]
    for name in {re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-"), repo_name, f"{repo_name}-game"}:
        obj = deployment(name, image)
        server._stamp_workload(obj, name)
        stage.append(obj)
bad = [o["metadata"]["name"] for o in stage if P.search(cel_text(o))]
check(len(games) >= 4 and not bad,
      f"the {len(games)} stage images the agent prompt names ({', '.join(g for g, _ in games)}) pass as Deployments "
      f"named for the game or the image, with deploy_app's stamped labels (refused: {bad})")

objects, unread = [], []
for path in sorted(p for p in (REPO / "gitops").rglob("*") if p.suffix in (".yaml", ".yml") and p.is_file()):
    if path.parent == REPO / "gitops/bootstrap/templates":
        continue  # Helm templates, which render Applications in argocd, not objects in agent
    try:
        objects += [(path, d) for d in yaml.safe_load_all(path.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and isinstance(d.get("metadata"), dict)]
    except yaml.YAMLError as e:
        unread.append(f"{path.relative_to(REPO)}: {e}")
fixes = next(d for _, d in objects if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes")
for key, text in fixes["data"].items():
    objects += [(RESOURCES, d) for d in yaml.safe_load_all(text) if isinstance(d, dict) and d.get("metadata")]
bad = [f"{p.relative_to(REPO)}:{d.get('kind')}/{d['metadata'].get('name')}" for p, d in objects if P.search(cel_text(d))]
check(len(objects) > 150 and not unread and not bad,
      f"all {len(objects)} objects under gitops/ and in the terminal's challenge files pass, so Argo CD and the "
      f"switches are never refused (refused: {bad[:5]}; unreadable: {unread})")


def cel_cost(text: str) -> int:
    """What Kubernetes' CEL charges matches() on text with this pattern (k8s.io/apiserver/pkg/cel/library/cost.go):
    0.1 a character of the text, plus one, times 0.25 a character of the pattern."""
    return math.ceil((1 + len(text)) * 0.1) * math.ceil(len(pattern) * 0.25)


# A Job in agent, 374 characters of name and labels, was the longest a stage identity had written on either cluster on
# 2026-11-11 (#1316); the room's Jokers and the stage images are above, and every object under gitops/ is here.
longest = max([cel_text(d) for _, d in objects] + [cel_text(j) for j in jokers] + [cel_text(o) for o in stage]
              + ["x" * 374], key=len)
check(cel_cost(longest) * 3 // 2 <= 1_000_000,
      f"the longest name and labels here ({len(longest)} characters) cost {cel_cost(longest):,} of CEL's 1,000,000 a "
      f"call with half again to spare; the budget is about {int(1_000_000 / math.ceil(len(pattern) * 0.25) * 10):,} "
      "characters")

refused_name, refused_label, terms = [], [], corpus.terms("proposed")
for term in terms:
    word = floor.fold(term)[0]
    if not all(c.isascii() and (c.isalnum() or c in " -_.") for c in word):
        continue  # a term with a letter outside ASCII ("ß", the finger) or a symbol ("!") cannot be spelt in a name
    slug = re.sub(r"[^a-z0-9._-]+", "-", word).strip("-")
    refused_name.append(bool(P.search(cel_text(deployment(f"joker-{slug}", "x")))))
    obj = deployment("joker-agatha-the-banshee", "x")
    obj["spec"]["template"]["metadata"]["labels"]["mood"] = f"very-{slug}"
    refused_label.append(bool(P.search(cel_text(obj))))
check(len(refused_name) > 1200 and all(refused_name) and all(refused_label),
      f"each of the {len(refused_name)} ASCII terms is refused in a Deployment's name and in a pod "
      f"template label (of {len(terms)} terms; {refused_name.count(False)} names and "
      f"{refused_label.count(False)} labels got through)")
joined = cel_text({"metadata": {"name": "a", "labels": {"x": "f", "y": "u"}}})
check(joined == "a/x=f/y=u///", "label pairs join with '/', which ends a word for the pattern but is not one of its "
                                "separators, so letters in different labels never spell a term together")

print("== 4. guardrails-k8s-off, guardrails-ai-off and the resets leave it in place ==")
for path in (*ENTRYPOINTS, FLEET):
    text = path.read_text(encoding="utf-8")
    check(not ADMISSION_WORDS.search(text),
          f"{path.relative_to(REPO)} names no admission policy, webhook or this policy (guardrails-k8s-off, guardrails-ai-off, "
          "reset-bot, desk-reset, beacon-reset, wall-reset)")
entry = need(ENTRYPOINTS[0], '_kg() { local st="$1" g="$2" c a p; shift 2')
kg = entry[entry.index("_kg() {"):entry.index("_guardrails() {")]
off_files = re.findall(r"off:\w+\)\s+c=\(\"\$@\" (?:apply|delete --ignore-not-found) -f \"\$HOME/challenges/([\w.-]+)\"\)",
                       kg)
check(sorted(off_files) == ["c1-network-policy.yaml", "c3-kubearmor-policy.yaml", "c8-broad-role.yaml"],
      f"guardrails-k8s-off applies or deletes ~/challenges/ files and nothing else: {sorted(off_files)}")
fix_text = fixes["data"]
check(all(f in fix_text and not ADMISSION_WORDS.search(fix_text[f]) for f in off_files),
      "none of those files, as the challenge-fixes ConfigMap ships them, holds an admission policy")
patched = re.findall(r'patch (\w+) "\$p"', kg)
check(patched == ["validatingpolicy"] and "for p in restrict-image-registries deny-external-registries" in kg,
      "guardrails-k8s-off's Kyverno step patches Kyverno's ValidatingPolicy (restrict-image-registries, "
      "deny-external-registries) alone, never a ValidatingAdmissionPolicy")
guards_off = entry[entry.index('cat > "$HOME/guardrails-ai-off"'):]
guards_off = guards_off[:guards_off.index("\nEOS\n")]
check("kubectl" not in guards_off and "_both _toggle" in guards_off and "_both _mcp off" in guards_off,
      "guardrails-ai-off runs guard-proxy's /toggle and the MCP tool switch alone, no kubectl of its own")

rbac_files = [*sorted(AI.glob("*.yaml")), *sorted((REPO / "gitops/guardrails-switch").glob("*.yaml"))]
grants, roles = [], []
for path in rbac_files:
    for d in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if not isinstance(d, dict) or d.get("kind") not in ("Role", "ClusterRole"):
            continue
        roles.append(d["metadata"]["name"])
        for rule in d.get("rules") or []:
            groups, res, verbs = (set(rule.get(k) or []) for k in ("apiGroups", "resources", "verbs"))
            if (groups & {"admissionregistration.k8s.io", "*"}) and verbs & WRITE_VERBS and (
                    "*" in res or any(r.startswith("validatingadmissionpolic") for r in res)):
                grants.append(f"{path.relative_to(REPO)}:{d['kind']}/{d['metadata']['name']}")
check({"workshop-agent", "console-terminal", "guardrails-switch-mcp"} <= set(roles) and not grants,
      f"no Role or ClusterRole in gitops/ai-layer or gitops/guardrails-switch grants a write on admission policies, so "
      f"neither the bot, the terminal nor the switch can lift it ({len(roles)} roles read; grants: {grants})")

print()
if failures:
    print(f"FAIL: {len(failures)} check(s) failed")
    sys.exit(1)
print("ALL CODE-OF-CONDUCT ADMISSION CHECKS PASS")
