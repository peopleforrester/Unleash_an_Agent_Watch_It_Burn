# ABOUTME: Holds #1220: on kubecon-private the admin cluster's own desk hosts answer 307 to the one desk and deployments
# ABOUTME: page, by an exact-name nginx server nginx picks before console.conf's, and every other profile renders without it.
"""Offline checks for #1220. No cluster, no network, no nginx binary.

Since #1145 both KubeCon bots read support.burritobot.co and report to deployments.burritobot.co (#1158). The admin
cluster's own hosts, support-burritobot-private and deployments-burritobot-private, were still served by its own
fake-ticket, so a ticket filed there was one the admin bot never read. The public-desk component, which only
kubecon-private adds, now merges private-desk-redirect.conf into console-conf, beside console.conf's default.conf:

  1. the file: two servers, on the listeners and certificate console.conf's desk servers use, each naming exact hosts
     (the two private hosts on both domains) and returning 307 to the one desk's host with the request's path and query;
  2. nginx's server choice, done here the way nginx does it (an exact name first, then the first regular expression in
     the order the files are read, then the default server), over console.conf and the file: the private hosts reach
     the redirect, and every public desk name, a lookalike and the bot host still reach the server they reached before;
  3. the component: it merges the file into console-conf under a name nginx's conf.d/*.conf include reads and the
     desk-remote-reports include does not, and each profile's console-conf has it exactly when desk.usePublicDesk is
     true, which is kubecon-private alone.

verify/test_bootstrap_chart_render.py builds the same component with the pinned kustomize. Run 19413 ran the file under
the console's own nginx 1.27.5 on watch-it-burn-private (decisions.md, #1220).
"""
from __future__ import annotations

import fnmatch
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import support_desk_hosts as sd  # noqa: E402
from bootstrap_chart import (DESK_REMOTE_COMPONENT, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, PUBLIC_DESK_COMPONENT,  # noqa: E402
                             REPO, REVISION, ai_layer_for, all_profiles, app_names, use_public_desk)

AI = REPO / "gitops/ai-layer"
COMPONENT = AI / PUBLIC_DESK_COMPONENT
FILE_NAME = "private-desk-redirect.conf"
REDIRECT = (COMPONENT / FILE_NAME).read_text(encoding="utf-8")
CONF = (AI / "console.conf").read_text(encoding="utf-8")
COMP = yaml.safe_load((COMPONENT / "kustomization.yaml").read_text(encoding="utf-8"))
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
REMOTE_LOCATIONS = "desk-remote-report.locations"
# The console.conf headings this test cuts the desk servers on (tests own their inputs, #797).
DESK_ANCHOR = "# Challenge 6's ticket desk (2026-10-28 call, #685)"
PAGE_ANCHOR = "# Challenge 2's deployments page (#773)"
REGISTRY_ANCHOR = "# The internal registry (#774)"
for anchor in (DESK_ANCHOR, PAGE_ANCHOR, REGISTRY_ANCHOR):
    if anchor not in CONF:
        print(f"FAILED: the anchor {anchor!r} is not in gitops/ai-layer/console.conf; reword this test with it")
        sys.exit(1)
DESK_SERVER = CONF[CONF.index(DESK_ANCHOR):CONF.index(PAGE_ANCHOR)]
PAGE_SERVER = CONF[CONF.index(PAGE_ANCHOR):CONF.index(REGISTRY_ANCHOR)]
PRIVATE_SUPPORT, PRIVATE_DEPLOYMENTS = sd.PRIVATE_DESK_HOSTS
ONE_DESK, ONE_PAGE = sd.DESK[0], sd.DEPLOYMENTS


def twin(host: str) -> str:
    """The same host on the old domain, which console.conf's servers also answer."""
    return host.removesuffix(".burritobot.co") + ".agenticburn.com"


failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def unquoted(text: str) -> str:
    """The config with comments dropped and every quoted string blanked, as nginx's own reader skips them: console.conf
    returns HTML in quotes, whose CSS carries # and braces that are no part of the config's structure."""
    out, quote, comment = [], "", False
    for i, ch in enumerate(text):
        if comment:
            comment = ch != "\n"
            out.append(ch if ch == "\n" else " ")
        elif quote:
            if ch == quote and text[i - 1] != "\\":
                quote = ""
            out.append(ch if ch == "\n" else " ")
        elif ch in "'\"":
            quote = ch
            out.append(" ")
        elif ch == "#":
            comment = True
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def servers(text: str) -> list[str]:
    """Each top-level server { ... } block's body, read outside comments and quoted strings, braces counted."""
    text = unquoted(text)
    out, i = [], 0
    for m in re.finditer(r"(?m)^server\s*\{", text):
        if m.start() < i:
            continue
        depth, j = 0, m.end() - 1
        while j < len(text):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                break
            j += 1
        out.append(text[m.end():j])
        i = j
    return out


def names(block: str) -> list[str]:
    m = re.search(r"^\s*server_name\s+([^;]+);", block, re.M)
    return m.group(1).split() if m else []


def directives(block: str, name: str) -> list[str]:
    return [" ".join(v.split()) for v in re.findall(rf"^\s*{name}\s+([^;]+);", block, re.M)]


print("== the redirect file: two exact-name servers, each a 307 to the one desk's same path ==")
blocks = servers(REDIRECT)
check("the file holds two servers", len(blocks) == 2, str(len(blocks)))
by_target = {}
for b in blocks:
    ret = directives(b, "return")
    by_target[ret[0] if ret else ""] = b
want = {f"307 https://{ONE_DESK}$request_uri": [PRIVATE_SUPPORT, twin(PRIVATE_SUPPORT)],
        f"307 https://{ONE_PAGE}$request_uri": [PRIVATE_DEPLOYMENTS, twin(PRIVATE_DEPLOYMENTS)]}
check("one returns 307 to the one desk and one to the one page, each with $request_uri", sorted(by_target) == sorted(want),
      str(sorted(by_target)))
for target, hosts in want.items():
    b = by_target.get(target, "")
    check(f"{target.split()[1]}: named for {hosts}, exactly", names(b) == hosts, str(names(b)))
    check(f"{target.split()[1]}: every name is exact, no regular expression or wildcard",
          bool(names(b)) and not any(n.startswith("~") or "*" in n for n in names(b)), str(names(b)))
    check(f"{target.split()[1]}: the redirect is its only answer, no location or proxy",
          re.search(r"^\s*(location|proxy_pass|include)\b", b, re.M) is None and directives(b, "return") == [target])
    check(f"{target.split()[1]}: 307, so a POST keeps its method and body and no browser keeps it for good",
          target.startswith("307 "))
desk_listen = directives(DESK_SERVER, "listen") + directives(DESK_SERVER, "ssl_certificate") + \
    directives(DESK_SERVER, "ssl_certificate_key")
for b in blocks:
    got = directives(b, "listen") + directives(b, "ssl_certificate") + directives(b, "ssl_certificate_key")
    check(f"{names(b)[:1]}: the same listeners and certificate as console.conf's desk server", got == desk_listen,
          f"{got} != {desk_listen}")
all_names = [n for b in blocks for n in names(b)]
check("no redirect target is a name the file serves, so nothing redirects to itself",
      ONE_DESK not in all_names and ONE_PAGE not in all_names, str(all_names))
check("the two private hosts are support_desk_hosts.PRIVATE_DESK_HOSTS",
      PRIVATE_SUPPORT.startswith("support-burritobot-private.") and
      PRIVATE_DEPLOYMENTS.startswith("deployments-burritobot-private."), str(sd.PRIVATE_DESK_HOSTS))
check("the file has no http or events block", re.search(r"^\s*(http|events)\s*\{", unquoted(REDIRECT), re.M) is None)


print("== nginx's choice of server, over console.conf then the redirect file ==")
# conf.d/*.conf is read in name order: default.conf (console.conf), then the redirect file.
ORDER = [("console.conf", b) for b in servers(CONF)] + [(FILE_NAME, b) for b in blocks]
check("default.conf sorts before the redirect file, the order nginx's glob reads them", "default.conf" < FILE_NAME)


def chosen(host: str) -> tuple[str, str]:
    """The server nginx gives a Host: an exact name anywhere first, then the first matching regex in order, then the
    default server (server_name _). Returns (file, its first server_name)."""
    for f, b in ORDER:
        if host in [n for n in names(b) if not n.startswith("~")]:
            return f, names(b)[0]
    for f, b in ORDER:
        for n in names(b):
            if n.startswith("~") and re.search(n[1:], host):
                return f, n
    return next((f, names(b)[0]) for f, b in ORDER if "_" in names(b))


desk_name, page_name = names(servers(DESK_SERVER)[0])[0], names(servers(PAGE_SERVER)[0])[0]
for host in (PRIVATE_SUPPORT, twin(PRIVATE_SUPPORT)):
    f, n = chosen(host)
    check(f"{host}: console.conf's desk server would take it without the file", re.search(desk_name[1:], host) is not None)
    check(f"{host}: the redirect server takes it", (f, n) == (FILE_NAME, PRIVATE_SUPPORT), f"{f} {n}")
for host in (PRIVATE_DEPLOYMENTS, twin(PRIVATE_DEPLOYMENTS)):
    f, n = chosen(host)
    check(f"{host}: console.conf's deployments server would take it without the file",
          re.search(page_name[1:], host) is not None)
    check(f"{host}: the redirect server takes it", (f, n) == (FILE_NAME, PRIVATE_DEPLOYMENTS), f"{f} {n}")
for host in (*sd.DESK, "support-burritobot-private-x.burritobot.co", "support-burritobot-privatex.burritobot.co"):
    check(f"{host}: still console.conf's desk server", chosen(host) == ("console.conf", desk_name), str(chosen(host)))
for host in (ONE_PAGE, "deployments-attackme.burritobot.co", "deployments-burritobot-private-b01.burritobot.co"):
    check(f"{host}: still console.conf's deployments server", chosen(host) == ("console.conf", page_name),
          str(chosen(host)))
for host in ("burritobot-private.burritobot.co", "burritobot-private.agenticburn.com"):
    check(f"{host}, the admin bot's own host: still console.conf's default server",
          chosen(host) == ("console.conf", "_"), str(chosen(host)))


print("== the component, and each profile's console-conf ==")
gen = [g for g in COMP.get("configMapGenerator") or [] if g.get("name") == "console-conf"]
check("the public-desk component merges the file alone into console-conf",
      gen == [{"name": "console-conf", "behavior": "merge", "files": [FILE_NAME]}], str(gen))
check("its name is one nginx's include /etc/nginx/conf.d/*.conf reads", fnmatch.fnmatchcase(FILE_NAME, "*.conf"))
inc = re.findall(r"^\s*include\s+/etc/nginx/conf\.d/(\S+);", CONF, re.M)
check("and not one console.conf's desk-remote-reports include reads", bool(inc) and
      not any(fnmatch.fnmatchcase(FILE_NAME, p) for p in inc), str(inc))
base_conf = next((g for g in KUST["configMapGenerator"] if g["name"] == "console-conf"), {})
base_keys = [f.partition("=")[0] if "=" in f else pathlib.Path(f).name for f in base_conf.get("files", [])]
check("the base console-conf is default.conf alone", base_keys == ["default.conf"], str(base_keys))


def components(profile: str) -> list[str]:
    app = yaml.safe_load(ai_layer_for(profile).replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR))
    return list(app["spec"]["source"].get("kustomize", {}).get("components") or [])


def conf_keys(comps: list[str]) -> list[str]:
    keys = list(base_keys)
    for c in comps:
        doc = yaml.safe_load((AI / c / "kustomization.yaml").read_text(encoding="utf-8"))
        for g in doc.get("configMapGenerator") or []:
            if g.get("name") == "console-conf":
                keys += [f.partition("=")[0] if "=" in f else pathlib.Path(f).name for f in g.get("files", [])]
    return keys


rendered = [p for p in all_profiles() if "ai-layer" in app_names(p)]
check("kubecon-private, kubecon-community and the attendee profile render the ai-layer",
      {"attendee", "kubecon-private", "kubecon-community"} <= set(rendered), str(rendered))
for profile in rendered:
    on = profile == "kubecon-private"
    comps = components(profile)
    keys = conf_keys(comps)
    check(f"{profile}: desk.usePublicDesk is {on}", use_public_desk(profile) is on)
    check(f"{profile}: console-conf {'has' if on else 'has no'} {FILE_NAME} {keys}", (FILE_NAME in keys) is on)
    if profile == "kubecon-community":
        check(f"{profile}: its own desk keeps its remote routes and no redirect",
              DESK_REMOTE_COMPONENT in comps and REMOTE_LOCATIONS in keys and FILE_NAME not in keys, str(keys))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("On kubecon-private the admin cluster's own desk hosts answer 307 to the one desk and deployments page, and every "
      "other profile renders without the redirect (#1220).")
