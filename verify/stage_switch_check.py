# ABOUTME: The judging half of the Night Before stage-switch check (#1182, part of #1146): from both KubeCon clusters'
# ABOUTME: /controls before and after a switch and from the read the switch prints, PASS or FAIL per cluster; and the start state.
"""Judges each stage switch on each KubeCon cluster from guard-proxy's /controls. No cluster access of its own.

The presenters type every stage switch in the private cluster's terminal, and the room plays on the public bot. A
switch has reached a cluster when every /controls field it owns reads off before it and on after it. The caller
(verify/stage_switch_run.py, #1183) reads https://burritobot-private.burritobot.co/controls and
https://attackme.burritobot.co/controls before and after each switch and hands the four reads here, keyed by cluster
("private", "community"). Each read may be the parsed JSON, its text or bytes, or None for a read that failed.

The switches, in talk order, and the fields each owns (guard-proxy proxy.py: the `/controls` handler sends
{"ai": GUARDS, "infra": read_controls(), "host": WIB_PUBLIC_HOST}). Since #1350 every stage switch is
guardrails-<name>-on, with guardrails-<name>-off its pair (OFF), and the old names are aliases the terminal keeps (#1351
moved this check onto the new names). The Kubernetes one is guardrails-k8s-on, never "kates" (Michael's ruling on #1350):

    guardrails-k8s-on     segment 3    infra.rbac_scoped, infra.kyverno, infra.kubearmor, infra.networkpolicy
    guardrails-agency-on  Challenge 3  infra.agency_scoped, the least-privilege Role (guard-proxy-agenticburn#76)
    guardrails-input-on   Challenge 3  ai.input_blocklist, ai.input_classifier
    guardrails-mcp-on     Challenge 4  infra.tool_allowlist

`agency_scoped` reached /controls with the guard-proxy repin (both clusters send it, read on 2026-11-11). Were it gone,
guardrails-agency-on is judged FAIL, naming #1132, on each cluster where it is missing. A missing field is never a skip
or a PASS. guard-proxy reads a field it could not measure as null; null is neither off nor on, so a switch whose field
reads null before or after it fails too.

Each switch also ends on the terminal's own read of both clusters' /controls (`_controls` in the web-terminal
entrypoint, #1349), printed by name. judge_printed reads that block back (printed_controls) and judges it the same way:
every field the switch owns reads ON, or off for an -off switch, on each cluster, as the switch itself printed it.

The start state, before the first switch and again after the -off switches, is every one of those fields
off on both clusters. Falco is outside it: it is not a switch, and the private cluster runs it (read on at 2026-11-07
19:40 CST) while the community cluster does not. The other AI guards (output, budget, topic) are not stage switches
and are not judged here.

A read whose "host" names a different cluster than the one it is filed under fails, by kubecon_probe's identity_name,
so a swapped pair of reads is not judged as each other's.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kubecon_probe import FAIL, PASS, identity_name  # noqa: E402

# Each cluster the switches must reach, by the name the caller files its reads under, and the host it is read from.
CLUSTERS = {
    "private": "burritobot-private.burritobot.co",
    "community": "attackme.burritobot.co",
}

# Talk order. Each field is (section, key) in guard-proxy's /controls JSON.
SWITCHES: dict[str, tuple[tuple[str, str], ...]] = {
    "guardrails-k8s-on": (("infra", "rbac_scoped"), ("infra", "kyverno"), ("infra", "kubearmor"),
                          ("infra", "networkpolicy")),
    "guardrails-agency-on": (("infra", "agency_scoped"),),
    "guardrails-input-on": (("ai", "input_blocklist"), ("ai", "input_classifier")),
    "guardrails-mcp-on": (("infra", "tool_allowlist"),),
}
# Each switch's pair, which turns the same fields off.
OFF = {name: name[:-len("-on")] + "-off" for name in SWITCHES}

# How the terminal's _controls names each /controls field when it prints a cluster's read (the GROUPS table of _ctlfmt in
# gitops/ai-layer/web-terminal/entrypoint.sh; verify/test_stage_switch_check.py runs that code and reads its output back).
PRINTED_LABELS: dict[tuple[str, str], str] = {
    ("ai", "output"): "output", ("ai", "input_blocklist"): "input block-list",
    ("ai", "input_classifier"): "injection classifier", ("ai", "budget"): "budget cap", ("ai", "topic"): "on-topic",
    ("infra", "networkpolicy"): "NetworkPolicy", ("infra", "kyverno"): "Kyverno", ("infra", "kubearmor"): "KubeArmor",
    ("infra", "falco"): "Falco", ("infra", "tool_allowlist"): "tool allow-list", ("infra", "rbac_scoped"): "RBAC scope",
    ("infra", "agency_scoped"): "least privilege",
}
_PRINTED_GROUP = {"AI guards": "ai", "Kubernetes": "infra"}
PRINTED_HEADER = "Read back from guard-proxy's /controls"

# A field the pinned guard-proxy does not send yet, and what it waits on.
WAITS_ON = {
    ("infra", "agency_scoped"): ("#1132 (guard-proxy-agenticburn#76 added it on guard-proxy's staging; it reaches "
                                 "/controls once this repo repins the gitops/ai-layer/guard-proxy submodule)"),
}

_MISSING = object()


class Verdict(NamedTuple):
    result: str  # PASS or FAIL
    reason: str


def _name(field: tuple[str, str]) -> str:
    return ".".join(field)


def read_controls(raw: Any) -> tuple[dict | None, str]:
    """One cluster's /controls read as guard-proxy sends it: (controls, "") or (None, why it cannot be judged)."""
    if raw is None:
        return None, "/controls could not be read (no response)"
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return None, f"/controls is not UTF-8 text ({e})"
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            return None, f"/controls is not JSON ({e.msg} at {e.pos}): {raw.strip()[:80]!r}"
    if not isinstance(raw, dict):
        return None, f"/controls is a JSON {type(raw).__name__}, not an object"
    bad = [s for s in ("ai", "infra") if not isinstance(raw.get(s), dict)]
    if bad:
        return None, f"/controls has no {' or '.join(bad)} object; is this a guard-proxy?"
    return raw, ""


def _field(controls: dict, field: tuple[str, str]) -> Any:
    section, key = field
    return controls[section].get(key, _MISSING)


def _read(cluster: str, raw: Any, when: str) -> tuple[dict | None, str]:
    """read_controls, plus the identity check: the read filed under a cluster must answer as that cluster."""
    controls, why = read_controls(raw)
    if controls is None:
        return None, f"{why} {when}"
    host = controls.get("host")
    if host and identity_name(host) != identity_name(CLUSTERS[cluster]):
        return None, f"the /controls read {when} answers as {host!r}, not {CLUSTERS[cluster]}"
    return controls, ""


def _missing(field: tuple[str, str], when: str) -> str:
    waits = WAITS_ON.get(field)
    tail = f"; it waits on {waits}" if waits else "; guard-proxy's /controls no longer sends it"
    return f"/controls {when} does not carry {_name(field)}{tail}"


def _switch_on_cluster(switch: str, cluster: str, before_raw: Any, after_raw: Any) -> Verdict:
    before, why = _read(cluster, before_raw, "before the switch")
    if before is None:
        return Verdict(FAIL, why)
    after, why = _read(cluster, after_raw, "after the switch")
    if after is None:
        return Verdict(FAIL, why)
    bad = []
    for field in SWITCHES[switch]:
        b, a = _field(before, field), _field(after, field)
        if a is _MISSING:
            bad.append(_missing(field, "after the switch"))
            continue
        if b is _MISSING:
            bad.append(_missing(field, "before the switch"))
        elif b is True:
            bad.append(f"{_name(field)} was already on before the switch, so the switch was not seen to turn it on")
        elif b is not False:
            bad.append(f"{_name(field)} read {json.dumps(b)} before the switch, not false")
        if a is not True:
            bad.append(f"{_name(field)} reads {json.dumps(a)} after the switch, not true")
    if bad:
        return Verdict(FAIL, "; ".join(bad))
    return Verdict(PASS, f"{switch} turned on {', '.join(_name(f) for f in SWITCHES[switch])}")


def judge_switch(switch: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Verdict]:
    """PASS on a cluster only when every field the switch owns read false before it and true after it there.

    `before` and `after` map each cluster name in CLUSTERS to that cluster's /controls read; a cluster with no read
    is judged on None. An unknown switch name is the caller's mistake and raises ValueError, not a verdict."""
    if switch not in SWITCHES:
        raise ValueError(f"unknown stage switch {switch!r}; the switches are {', '.join(SWITCHES)}")
    return {c: _switch_on_cluster(switch, c, before.get(c), after.get(c)) for c in CLUSTERS}


def _start_on_cluster(cluster: str, raw: Any) -> Verdict:
    controls, why = _read(cluster, raw, "at the start-state check")
    if controls is None:
        return Verdict(FAIL, why)
    bad = []
    for switch, fields in SWITCHES.items():
        for field in fields:
            v = _field(controls, field)
            if v is _MISSING:
                bad.append(f"{_missing(field, 'at the start-state check')}, so it cannot be read as off ({switch})")
            elif v is not False:
                bad.append(f"{_name(field)} reads {json.dumps(v)}, not false ({switch})")
    if bad:
        return Verdict(FAIL, "; ".join(bad))
    return Verdict(PASS, "every stage switch's field reads off (Falco not judged)")


def judge_start_state(controls: dict[str, Any]) -> dict[str, Verdict]:
    """Both clusters back at the start state, after the -off switches (OFF): every field every switch owns
    reads false. FAIL names each field that does not, on its cluster."""
    return {c: _start_on_cluster(c, controls.get(c)) for c in CLUSTERS}


# --- the read each switch prints -------------------------------------------------------------------------------------
_PRINTED_FIELD = {(field[0], label): field for field, label in PRINTED_LABELS.items()}
_PRINTED_STATE = {"ON": True, "off": False, "not measured": None}


def _printed_names(text: str) -> list[str]:
    text = text.strip()
    return [] if text in ("", "none") else text.split(", ")


def printed_controls(out: str) -> dict[str, dict[tuple[str, str], bool | None]]:
    """The last /controls read a terminal switch printed (`_controls`), per cluster in CLUSTERS: each field it showed,
    True for ON, False for off, None for not measured. A cluster is known by the host its line prints; one the read
    names by no host of CLUSTERS, or does not show, is left out, never guessed."""
    lines = out.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(PRINTED_HEADER)]
    if not starts:
        return {}
    reads: dict[str, dict[tuple[str, str], bool | None]] = {}
    current: dict | None = None
    for line in lines[starts[-1] + 1:]:
        body = line.strip()
        if line.startswith("    ") and current is not None:
            group = next((g for g in _PRINTED_GROUP if body.startswith(g + " ")), None)
            if group is None or "ON: " not in body or "   off: " not in body:
                continue
            section = _PRINTED_GROUP[group]
            rest = body.split("ON: ", 1)[1]
            on, rest = rest.split("   off: ", 1)
            off, _, unread = rest.partition("   not measured: ")
            for state, names in (("ON", on), ("off", off), ("not measured", unread)):
                for label in _printed_names(names):
                    current[_PRINTED_FIELD.get((section, label), (section, label))] = _PRINTED_STATE[state]
        elif line.startswith("  ") and not line.startswith("    ") and ", " in body and not body.startswith("⚠"):
            host = body.rsplit(", ", 1)[1]
            cluster = next((c for c, h in CLUSTERS.items() if identity_name(h) == identity_name(host)), None)
            current = reads.setdefault(cluster, {}) if cluster else None
        elif not line.startswith("  "):
            break
    return reads


def judge_printed(name: str, out: str) -> dict[str, Verdict]:
    """The read a switch printed at its end, judged per cluster: PASS when every field the switch owns shows ON (off
    for an -off switch) on that cluster. `name` is a switch in SWITCHES or its pair in OFF; anything else raises."""
    on_name = next((n for n, off in OFF.items() if off == name), name)
    if on_name not in SWITCHES:
        raise ValueError(f"unknown stage switch {name!r}; the switches are {', '.join([*SWITCHES, *OFF.values()])}")
    want = on_name == name
    shown = "ON" if want else "off"
    reads = printed_controls(out)
    verdicts = {}
    for cluster, host in CLUSTERS.items():
        read = reads.get(cluster)
        if read is None:
            warn = [ln.strip() for ln in out.splitlines() if ln.lstrip().startswith("⚠") and "/controls" in ln]
            verdicts[cluster] = Verdict(FAIL, f"{name}'s closing /controls read does not show {host}"
                                              + (f": {warn[-1]}" if warn else ""))
            continue
        bad = []
        for field in SWITCHES[on_name]:
            if field not in read:
                bad.append(f"{PRINTED_LABELS[field]} is not in it")
            elif read[field] is not want:
                was = {True: "ON", False: "off", None: "not measured"}[read[field]]
                bad.append(f"{PRINTED_LABELS[field]} printed {was}, not {shown}")
        labels = ", ".join(PRINTED_LABELS[f] for f in SWITCHES[on_name])
        verdicts[cluster] = (Verdict(FAIL, f"{name}'s closing /controls read for {host}: " + "; ".join(bad)) if bad else
                             Verdict(PASS, f"{name} printed {labels} {shown} for {host}"))
    return verdicts
