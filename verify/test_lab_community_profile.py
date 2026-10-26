# ABOUTME: On the Community cluster (burn profile) the lab page must not offer a command for a control that is
# ABOUTME: not installed there, nor claim a layer that does not exist. Pins the data-full / data-burn split (#283).
"""Keeps the lab page honest on the Community cluster (#283).

The same lab.html ships to every cluster. A student cluster has Kyverno, Falco and Istio installed, with
the student's controls unarmed until they apply them. The Community cluster (attackme) runs the burn
profile, which never installs them at all. Opened there, the C2 fix printed three consecutive "server
doesn't have a resource type" errors, the C3 Falco watch returned nothing, and the reset section described
a Kyverno layer that is not on the cluster.

The page now marks full-profile-only content with data-full (hidden on the Community cluster) and puts
what is true there under data-burn. This test pins three things: the burn profile really does lack what
the notes say it lacks, every command that needs an absent component is hidden there, and each affected
section says what is actually present instead.
"""
from __future__ import annotations

import html.parser
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
BB = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import APPS, app_names  # noqa: E402

AI_LAYER = yaml.safe_load((APPS / "ai-layer.yaml").read_text(encoding="utf-8"))
DEPLOY = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# --- the profile the notes describe ---------------------------------------------------------------------
apps = set(app_names("burn"))

print("== the burn profile lacks exactly what the Community notes say it lacks ==")
# If the burn profile ever gains one of these, the notes become the false claim, so this fails first.
for absent in ("kyverno", "kyverno-policies", "falco", "falco-talon", "falcosidekick", "istio",
               "network-policies", "kubearmor-policies"):
    check(f"{absent} is not installed on the Community cluster", absent not in apps)
check("the KubeArmor engine is (so the C3 prevention fix still works there)", "kubearmor" in apps)
check("the ai-layer is (so the guard-proxy Argo CD restores exists there)", "ai-layer" in apps)
check("the ai-layer Application self-heals, so Argo CD restoring a deleted guard-proxy is true there",
      AI_LAYER["spec"]["syncPolicy"]["automated"].get("selfHeal") is True)
check("and so does the lab-bootstrap root deploy-full-idp.sh applies over it",
      "name: lab-bootstrap" in DEPLOY and "      selfHeal: true\n" in DEPLOY[DEPLOY.index("name: lab-bootstrap"):])


# --- parse the page, remembering which data-full / data-burn region each piece of text sits in -----------
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Walk(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.texts: list[tuple[str, bool, bool]] = []      # (text, under data-full, under data-burn)
        self.cmds: list[dict] = []                          # open .cmd blocks being collected
        self.done_cmds: list[tuple[str, bool, bool]] = []

    def _flags(self) -> tuple[bool, bool]:
        return (any("data-full" in a for _, a in self.stack), any("data-burn" in a for _, a in self.stack))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in VOID:
            return
        self.stack.append((tag, a))
        if "cmd" in (a.get("class") or "").split():
            full, burn = self._flags()
            self.cmds.append({"depth": len(self.stack), "text": "", "full": full, "burn": burn})

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            t, _ = self.stack.pop()
            if self.cmds and self.cmds[-1]["depth"] == len(self.stack) + 1:
                c = self.cmds.pop()
                self.done_cmds.append((c["text"], c["full"], c["burn"]))
            if t == tag:
                break

    def handle_data(self, data):
        full, burn = self._flags()
        self.texts.append((data, full, burn))
        for c in self.cmds:
            c["text"] += data


w = Walk()
w.feed(LAB)

print("== no command that needs an absent component is shown on the Community cluster ==")
NEEDS_ABSENT = re.compile(r"validatingpolic|clusterpolic|policyreport|kyverno\.io|falco|block-argocd-drift", re.I)
needing = [(t, f) for t, f, _ in w.done_cmds if NEEDS_ABSENT.search(t)]
check("the page still has the full-profile commands (the full lab is unchanged)", len(needing) >= 5)
for text, full in needing:
    check(f"hidden on the Community cluster: {text.strip()[:70]!r}", full)
check("the get-by-name watch, which exits NotFound once the delete succeeds, is full-profile only",
      all(f for t, f, _ in w.done_cmds if "get deploy guard-proxy -w" in t))
burn_cmds = [t for t, _, b in w.done_cmds if b]
check("the Community reset has its own command without the Kyverno line",
      any("delete kubearmorpolicy block-recipe-snoop" in t and "validatingpolicy" not in t for t in burn_cmds))
check("the Community delete-and-watch watches by field selector",
      any("--field-selector metadata.name=guard-proxy -w" in t for t in burn_cmds))

print("== no sentence claiming an absent layer is shown on the Community cluster ==")
FALSE_THERE = ("block-argocd-drift", "This cluster runs", "Three layers stand behind that", "refused outright",
               "Recipe Snoop", "Falco alert goes quiet", "one of each kind", "full internal developer platform",
               "The one you are about to apply", "Istio ambient mesh")
for phrase in FALSE_THERE:
    hits = [(f, b) for t, f, b in w.texts if phrase in t]
    check(f"{phrase!r} appears, and only where it is hidden on the Community cluster",
          bool(hits) and all(f for f, _ in hits))

print("== each affected section says what IS on the Community cluster ==")


def burn_text_between(start: str, end: str) -> str:
    a, b = LAB.find(start), LAB.find(end)
    assert a != -1 and b != -1 and a < b, f"could not slice {start!r}..{end!r}"
    sub = Walk()
    sub.feed(LAB[a:b])
    return " ".join(" ".join(t.split()) for t, _, burn in sub.texts if burn)


lede = burn_text_between("<h1>You are in.", "Challenge 1: Exfiltrate")
c2 = burn_text_between("Challenge 2: Deploy a villain", "Challenge 3: Get the secret")
c3 = burn_text_between("Challenge 3: Get the secret", "Challenge 4: Run up the bill")
reset = burn_text_between("Reset and explore", "</section>")
check("the top of the page says this is the Community cluster", "This is the Community cluster" in lede)
check("C2 says no admission controller is installed, so there is nothing to fix it with",
      "nothing to fix this with" in c2 and "No admission controller is installed" in c2)
check("C2 says that is the point of the Community cluster", "That is the point of the Community cluster" in c2)
check("C3 says detection is not installed", "is not on this cluster" in c3 and "Falco" in c3)
check("C3 says the prevention half works", "The prevention half is real" in c3 and "KubeArmor" in c3)
check("Reset says the delete goes through", "your delete goes through" in reset)
check("Reset names the layers that exist, and how many", "Two layers stand behind that here, not three" in reset
      and "Argo CD" in reset and "BurritoBot's own account is not allowed to delete Deployments" in reset)
check("Reset says the Kyverno layer is not installed", "is not installed on this cluster" in reset)
everything_burn = " ".join(t for t, _, b in w.texts if b)
# Whitney's rule from the Community banner (#292): the room has not been told yet that they get their own
# cluster, and the Community cluster's own pages must not tell them.
check("no Community note spoils that each student gets a cluster",
      not re.search(r"your own cluster|student cluster|student BurritoBot", everything_burn, re.I))

print("== the page decides the profile from the cluster, the same way the Community banner does ==")
head = LAB[:LAB.find("</head>")]
check("the CSS hides data-burn by default", "[data-burn]{display:none}" in LAB)
check("the CSS shows data-burn on the Community cluster", 'html[data-profile="burn"] [data-burn]{display:revert}' in LAB)
check("the CSS hides data-full on the Community cluster", 'html[data-profile="burn"] [data-full]{display:none}' in LAB)
check("the hostname check runs in <head>, before the body renders",
      "markCommunity(location.hostname" in head and r"/^attackme\./i" in head)
check("the host guard-proxy reports is checked too", re.search(r"fetch\('/controls'.*?markCommunity\(c\.host\)", LAB, re.S)
      is not None)
check("the page hardcodes no cluster name", "watch-it-burn-community" not in re.sub(r"<!--.*?-->", "", LAB, flags=re.S))

print("== the BurritoBot badge strip does not light Falco where Falco does not exist ==")
check("the Falco badge is forced off on the Community cluster",
      "if(bd.key==='falco' && community) on = false;" in BB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All lab Community-profile checks passed.")
