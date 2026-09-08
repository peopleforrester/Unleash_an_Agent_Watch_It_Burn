# ABOUTME: Every technology the lab names links to that project's official documentation, so a student
# ABOUTME: meeting an unfamiliar tool can find out what it is without leaving the lab to guess a search.
"""Checks the lab page's technology links.

Offline by default: it asserts each named technology is linked and that the target is the documentation
root we intend. Pass WIB_CHECK_LINKS=1 to also fetch each URL, which is the half that catches an upstream
docs reorganisation. That is deliberately opt-in so the normal suite stays offline and fast.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = REPO / "gitops/ai-layer/web/lab.html"

# name -> official documentation ROOT. The landing page should explain what the thing IS; a deep link into
# a subsection is worse than no link, because the reader arrives mid-argument. All verified 200 on
# 2026-09-07.
DOCS = {
    "kagent": "https://kagent.dev/docs",
    "Kyverno": "https://kyverno.io/docs",
    "KubeArmor": "https://kubearmor.io/",
    "Falco": "https://falco.org/docs",
    "Falco-Talon": "https://falcosecurity.github.io/falco-talon/",
    "Argo CD": "https://argo-cd.readthedocs.io/en/stable/",
    "OpenTelemetry": "https://opentelemetry.io/docs",
    "agentgateway": "https://agentgateway.dev/docs/",
    "Bedrock": "https://docs.aws.amazon.com/bedrock/",
    "Datadog": "https://docs.datadoghq.com/",
    "ttyd": "https://github.com/tsl0922/ttyd",
    "cert-manager": "https://cert-manager.io/docs",
    "External Secrets": "https://external-secrets.io/",
}

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


def main() -> int:
    html = LAB.read_text(encoding="utf-8")

    print("== every technology the page names is a link ==")
    for name, want in DOCS.items():
        mentioned = re.search(r"(?<![>\w-])" + re.escape(name) + r"(?![\w-])", html) is not None
        if not mentioned:
            # Not naming a tool is fine; linking one we do not name is not the point of this test.
            print(f"  SKIP  {name} is not mentioned in the lab")
            continue
        linked = re.search(
            r'<a href="(https?://[^"]+)"[^>]*>' + re.escape(name) + r"</a>", html
        )
        check(f"{name} is linked by name", linked is not None)
        if linked:
            href = linked.group(1)
            check(f"{name} points at its documentation root ({want})", href.startswith(want.rstrip("/")))

    print("== Kubernetes concepts link to the official docs at first mention (#351) ==")
    # Whitney/Michael: the first time the lab names a concept an attendee may not know, link straight to
    # that project's own documentation, so a student has somewhere real to go and a presenter has a page
    # to click and narrate. These are k8s concepts (not named projects like the DOCS list above), so the
    # canonical concept page IS the right landing, not a docs root.
    CONCEPTS = {
        "admission controller": "https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/",
        "RBAC (Role)": "https://kubernetes.io/docs/reference/access-authn-authz/rbac/",
        "ServiceAccount": "https://kubernetes.io/docs/concepts/security/service-accounts/",
    }
    for name, url in CONCEPTS.items():
        linked = re.search(r'<a href="' + re.escape(url) + r'"([^>]*)>', html)
        check(f"{name} links to {url}", linked is not None)
        if linked:
            check(f"{name} opens in a new tab with noopener",
                  'target="_blank"' in linked.group(1) and "noopener" in linked.group(1))
    if os.environ.get("WIB_CHECK_LINKS") == "1":
        import urllib.request
        for name, url in CONCEPTS.items():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "wib-link-check"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    check(f"{name} -> {resp.status}", resp.status < 400)
            except Exception as exc:  # noqa: BLE001
                check(f"{name} -> {type(exc).__name__}", False)

    print("== the links behave themselves ==")
    # A link that steals the tab loses a student their place mid-challenge.
    for name in DOCS:
        m = re.search(r'<a href="https?://[^"]+"([^>]*)>' + re.escape(name) + r"</a>", html)
        if m:
            check(f"{name} opens in a new tab", 'target="_blank"' in m.group(1))
            check(f"{name} carries rel=noopener", "noopener" in m.group(1))

    if os.environ.get("WIB_CHECK_LINKS") == "1":
        print("== the documentation roots still resolve (network) ==")
        import urllib.request

        for name, url in DOCS.items():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "wib-link-check"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    check(f"{name} -> {resp.status}", resp.status < 400)
            except Exception as exc:  # noqa: BLE001 - any failure is a failure to report
                check(f"{name} -> {type(exc).__name__}", False)
    else:
        print("== network check skipped (set WIB_CHECK_LINKS=1 to fetch each URL) ==")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All documentation-link checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
