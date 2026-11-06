# ABOUTME: Static gate for #899: llm-guard-scanners carries LLM Guard's bearer-auth block, so the API checks the
# ABOUTME: AUTH_TOKEN it is given, and every caller sends that token from the same llm-guard-auth Secret.
"""Why this exists (#899).

Run 17422 on #455 found LLM Guard answering /analyze/prompt to a request with an empty bearer token. The vendored API
checks a token only when scanners.yml has an `auth:` block (images/llm-guard src/app/app.py, _check_auth_function:
with no auth config it returns a no-op check), and the llm-guard-scanners ConfigMap, which is mounted over the image's
config directory, had none. So the AUTH_TOKEN the Deployment set from the llm-guard-auth Secret was never read.

This holds, from the files alone:

  - scanners.yml has `auth: {type: http_bearer, token: ${AUTH_TOKEN:}}` in block style, and loaded with the vendored
    loader's own env-var regexes (read from images/llm-guard src/app/config.py) the token is the AUTH_TOKEN env value,
    and empty when it is unset, so an unset token refuses every call rather than opening the API;
  - the vendored API still skips auth without the block, so dropping the block reopens the guard;
  - llm-guard's AUTH_TOKEN, guard-proxy's and the MCP server's LLM_GUARD_TOKEN, and the attendee guard-proxy's, all
    come from llm-guard-auth's `token`, and kustomize generates that Secret with a non-empty token;
  - every caller of the API sends the bearer: guard-proxy's _post_guard, read_support_ticket's _ticket_flagged, and
    stage_traces.py, which calls guard-proxy's _post_guard in the pod. test_topic_guard_proxy.py and
    test_fake_ticket.py check the header each one sends against a fake LLM Guard.

The live half (a call with no token gets 401, guard-proxy's own calls pass) is in decisions.md's #899 entry. Offline.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
VENDORED = REPO / "images/llm-guard/src/app"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def need(path: pathlib.Path, literal: str) -> str:
    """The file's text, after checking it holds the literal this test reads it by."""
    text = path.read_text(encoding="utf-8")
    if literal not in text:
        print(f"FAIL  {path.relative_to(REPO)} no longer contains {literal!r}, which this test reads it by",
              file=sys.stderr)
        sys.exit(1)
    return text


docs = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text(encoding="utf-8")) if isinstance(d, dict)]


def obj(kind: str, name: str) -> dict:
    return next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name)


scanners_yml = obj("ConfigMap", "llm-guard-scanners")["data"]["scanners.yml"]

print("== the auth block is in scanners.yml ==")
plain = yaml.safe_load(scanners_yml)
check("scanners.yml has an auth block of type http_bearer whose token is ${AUTH_TOKEN:}",
      plain.get("auth") == {"type": "http_bearer", "token": "${AUTH_TOKEN:}"}, str(plain.get("auth")))
image_conf = yaml.safe_load(need(REPO / "images/llm-guard/src/config/scanners.yml", "auth:"))
check("the image's own scanners.yml, which the ConfigMap replaces, has the same block",
      image_conf.get("auth") == plain.get("auth"), str(image_conf.get("auth")))

print("== the vendored loader resolves it to AUTH_TOKEN ==")
config_src = need(VENDORED / "config.py", "_var_matcher = re.compile(")
var_matcher = re.compile(eval(re.search(r'^_var_matcher = re\.compile\((r".*")\)$', config_src, re.M).group(1)))
tag_matcher = re.compile(eval(re.search(r'^_tag_matcher = re\.compile\((r".*")\)$', config_src, re.M).group(1)))
check("config.py still substitutes ${NAME:default} from the env",
      'envparts = f"{match.group(1)}:".split(":")' in config_src
      and "os.environ.get(envparts[0], envparts[1])" in config_src)


class EnvLoader(yaml.SafeLoader):
    """yaml.SafeLoader with config.py's load_yaml resolver and constructor, on a subclass so nothing global moves."""


def _path_constructor(_loader, node):
    def replace_fn(match):
        envparts = f"{match.group(1)}:".split(":")
        return os.environ.get(envparts[0], envparts[1])
    return var_matcher.sub(replace_fn, node.value)


EnvLoader.add_implicit_resolver("!envvar", tag_matcher, None)
EnvLoader.add_constructor("!envvar", _path_constructor)

os.environ["AUTH_TOKEN"] = "witb-auth-test"
check("with AUTH_TOKEN set, the API is given that token",
      yaml.load(scanners_yml, Loader=EnvLoader).get("auth") == {"type": "http_bearer", "token": "witb-auth-test"})
del os.environ["AUTH_TOKEN"]
check("with AUTH_TOKEN unset, the token is empty, which no bearer header can match",
      yaml.load(scanners_yml, Loader=EnvLoader)["auth"]["token"] == "")
flow = scanners_yml.replace("auth:\n  type: http_bearer\n  token: ${AUTH_TOKEN:}\n",
                            "auth: { type: http_bearer, token: ${AUTH_TOKEN:} }\n")
check("(the one-line { } form this replaced would not parse: the anchor is there to swap)", flow != scanners_yml)
try:
    yaml.load(flow, Loader=EnvLoader)
    flow_parses = True
except yaml.YAMLError:
    flow_parses = False
check("the one-line { } form does not parse, which is why the block is in block style", not flow_parses)

print("== without the block the API checks nothing ==")
app_src = need(VENDORED / "app.py", "def _check_auth_function(")
auth_fn = app_src[app_src.index("def _check_auth_function("):app_src.index("return check_auth\n")]
check("_check_auth_function returns the no-op check when there is no auth config",
      re.search(r"if not auth_config:\n\s+return check_auth_noop", auth_fn) is not None)
check("and with http_bearer refuses a token that is not the configured one with 401",
      "credentials.credentials != auth_config.token" in auth_fn and "HTTP_401_UNAUTHORIZED" in auth_fn)
check("the API is built with the config's auth", "check_auth = _check_auth_function(config.auth)" in app_src)
for path in ("/analyze/prompt", "/analyze/output", "/scan/prompt", "/scan/output"):
    route = app_src[app_src.index(f'"{path}"'):]
    route = route[:route.index("@app.", 1) if "@app." in route[1:] else len(route)]
    check(f"{path} depends on check_auth", "Depends(check_auth)" in route)

print("== the token is one Secret, read by the API and sent by every caller ==")
SECRET_REF = {"name": "llm-guard-auth", "key": "token"}


def env_ref(deployment: dict, var: str) -> dict | None:
    for c in deployment["spec"]["template"]["spec"]["containers"]:
        for e in c.get("env") or []:
            if e["name"] == var:
                return (e.get("valueFrom") or {}).get("secretKeyRef")
    return None


check("llm-guard's AUTH_TOKEN is llm-guard-auth's token", env_ref(obj("Deployment", "llm-guard"), "AUTH_TOKEN") == SECRET_REF)
for name in ("guard-proxy", "workshop-mcp"):
    check(f"{name}'s LLM_GUARD_TOKEN is llm-guard-auth's token",
          env_ref(obj("Deployment", name), "LLM_GUARD_TOKEN") == SECRET_REF)
attendee = next(d for d in yaml.safe_load_all((REPO / "agent/gateway/guard-proxy/guard-proxy.yaml").read_text())
                if isinstance(d, dict) and d.get("kind") == "Deployment")
check("the attendee guard-proxy's LLM_GUARD_TOKEN is llm-guard-auth's token too",
      env_ref(attendee, "LLM_GUARD_TOKEN") == SECRET_REF)
kust = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
gen = next(s for s in kust.get("secretGenerator") or [] if s["name"] == "llm-guard-auth")
tokens = [lit.split("=", 1)[1].split("#")[0].strip() for lit in gen.get("literals") or [] if lit.startswith("token=")]
check("kustomize generates llm-guard-auth with one non-empty token", len(tokens) == 1 and tokens[0] != "", str(tokens))

proxy_src = need(AI / "guard-proxy/proxy.py", "def _post_guard(")
post_guard = proxy_src[proxy_src.index("def _post_guard("):proxy_src.index("def blocklisted(")]
check("guard-proxy's _post_guard sends Authorization: Bearer LLM_GUARD_TOKEN",
      '"Authorization": f"Bearer {LLM_GUARD_TOKEN}"' in post_guard)
check("guard-proxy reaches LLM Guard only through _post_guard",
      proxy_src.count("LLM_GUARD_URL}") == 1 and "{LLM_GUARD_URL}{path}" in post_guard)
mcp_src = need(AI / "workshop-mcp-server.py", "def _ticket_flagged(")
check("the MCP server's one LLM Guard call sends the bearer",
      mcp_src.count("LLM_GUARD_URL}/") == 1
      and "\"Authorization\": f\"Bearer {os.environ.get('LLM_GUARD_TOKEN', '')}\"" in mcp_src)
stage_src = (REPO / "verify/stage_traces.py").read_text(encoding="utf-8")
check("stage_traces.py asks LLM Guard only through guard-proxy's _post_guard, in the guard-proxy pod",
      "proxy._post_guard('/analyze/prompt'" in stage_src and "/analyze/prompt" not in stage_src.replace(
          "proxy._post_guard('/analyze/prompt'", ""))

print()
if failures:
    print(f"FAIL  {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("ALL LLM GUARD AUTH CHECKS GREEN")
