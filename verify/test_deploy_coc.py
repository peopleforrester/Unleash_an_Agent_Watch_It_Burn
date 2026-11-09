# ABOUTME: deploy_app refuses a manifest carrying a code-of-conduct term anywhere in it, and the desk's record_landing
# ABOUTME: masks one that still arrives, on the #1267 spike's floor, while every stage image and Joker name still lands.
"""#1269, part of #1267. The deployments page lists each deploy's name, image and witch name from record_landing
(gitops/ai-layer/ticket_site.py), which comes from what the bot passed to deploy_app (workshop-mcp-server.py), and the
Deployment lands in the cluster under its name. Both files carry the spike's proposed term floor
(docs/research/2026-11-09-coc-floor/floor.py, Floor("proposed")) as one block, always on.

This holds, with no cluster and no network:
  - the block is the same in both files, its terms are terms-proposed.rot13's, its pattern is floor.py's, and it finds
    and masks what floor.py does on the spike's abuse set and hard negatives;
  - deploy_app refuses a term in the name, a label key or value, an annotation, the image, an env value, args, the
    command, requested_by (the argument or the field the model writes into the manifest), a YAML manifest, a JSON
    \\u escape, a manifest that does not parse, and a bare name, for every term; the refusal says so plainly, names no
    term, applies nothing and reports nothing to the desk;
  - deploy_app still applies every game image BurritoBot's prompt deploys (Challenge 2, Tron among them), the KubeCon
    probe's c6-lands Joker manifest in the shape the probe sends it, and a Joker for every one of the stage's witch
    names, each credited to its witch;
  - record_landing, through the desk's own /landed and /remote-landed reader, stores no term in name, kind, image,
    witch, who or detail, the stage's rows unchanged, and a cluster read and /desk-forget still find a masked row.

The tests' own output names no term: a case is labelled by the field and the term's index in the list.
"""
from __future__ import annotations

import codecs
import importlib.util
import json
import pathlib
import re
import sys
import types

REPO = pathlib.Path(__file__).resolve().parents[1]
AI = REPO / "gitops/ai-layer"
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
SERVER_PY = AI / "workshop-mcp-server.py"
TICKET_PY = AI / "ticket_site.py"
sys.path.insert(0, str(SPIKE))

import corpus  # noqa: E402
import floor  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# --- the block, the same in both files ------------------------------------------------------------------------------
START = "# --- the code-of-conduct floor (#1269, part of #1267) "
END = "# --- end of the code-of-conduct floor "


def block(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    for anchor in (START, END):
        if text.count(anchor) != 1:
            raise SystemExit(f"{path.relative_to(REPO)}: the anchor {anchor!r} is there {text.count(anchor)} times, "
                             "not once; this test reads the code-of-conduct block between the two anchors")
    return text.split(START, 1)[1].split(END, 1)[0]


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        # No request in flight, as the real FastMCP has none outside its transport, so no X-Witch-Name either.
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
_spec = importlib.util.spec_from_file_location("workshop_mcp_deploy_coc", SERVER_PY)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)
_spec = importlib.util.spec_from_file_location("ticket_site_deploy_coc", TICKET_PY)
desk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(desk)

FLOOR = floor.Floor("proposed")
TERMS = corpus.terms("proposed")

print("== one floor, in both files, equal to the spike's ==")
check("the code-of-conduct block is the same text in workshop-mcp-server.py and ticket_site.py",
      block(SERVER_PY) == block(TICKET_PY))
check(f"its terms are terms-proposed.rot13's {len(TERMS)}, in order, in both files",
      list(server.COC_TERMS) == TERMS and list(desk.COC_TERMS) == TERMS,
      f"{len(server.COC_TERMS)} and {len(desk.COC_TERMS)} terms")
check("its pattern is floor.proposed_pattern()'s",
      server._COC_RE.pattern == floor.proposed_pattern().pattern == desk._COC_RE.pattern)
check("its look-alike table is floor.py's _HOMOGLYPH, the dotless i (U+0131) to i included (#1301)",
      server._COC_HOMOGLYPH == floor._HOMOGLYPH == desk._COC_HOMOGLYPH and floor._HOMOGLYPH.get(0x131) == ord("i"))
_texts = [t for _, t in corpus.abuse_set()] + corpus.hard_negatives() + TERMS
_differ = [i for i, t in enumerate(_texts)
           if not (server.coc_spans(t) == desk.coc_spans(t) == FLOOR.spans(t)
                   and server.coc_mask(t) == desk.coc_mask(t) == FLOOR.mask(t))]
check(f"it finds and masks what Floor('proposed') does on the {len(_texts)} abuse texts, hard negatives and terms",
      not _differ, f"text indexes that differ: {_differ[:10]}")
_missed = [i for i, t in enumerate(TERMS) if not server.coc_hit(t)]
check("it finds every term on its own", not _missed, f"term indexes missed: {_missed}")

# --- deploy_app -----------------------------------------------------------------------------------------------------
DISCOVERY = {
    "/apis/apps/v1": [{"name": "deployments", "kind": "Deployment"}, {"name": "statefulsets", "kind": "StatefulSet"}],
    "/api/v1": [{"name": "pods", "kind": "Pod"}, {"name": "services", "kind": "Service"},
                {"name": "configmaps", "kind": "ConfigMap"}],
}
applied: list[dict] = []
reports: list[dict] = []


def fake_req(method, path, body=None, content_type=None):
    if method == "GET" and path in DISCOVERY:
        return 200, json.dumps({"resources": DISCOVERY[path]})
    if method == "PATCH" and "/scale" not in path:
        applied.append({"path": path, "obj": json.loads(body)})
        return 201, body
    return 404, "{}"


class _NoTimer:
    """The Joker's scale-down timer, not started: a thread per Joker for an hour is not what this test is about."""

    def __init__(self, *a, **kw):
        self.daemon = True

    def start(self):
        pass


server._req = fake_req
server._report = lambda name, ok, detail, image="", requested_by="", kind="": reports.append(  # noqa: E731
    {"name": name, "ok": ok, "detail": detail, "image": image, "requested_by": requested_by, "kind": kind})
server._ns = lambda: "agent"  # noqa: E731
server.threading = types.SimpleNamespace(Timer=_NoTimer, Thread=server.threading.Thread,
                                         Event=server.threading.Event, Lock=server.threading.Lock)


def call(manifest: str, requested_by: str = ""):
    try:
        return server.deploy_app(manifest, requested_by), None
    except Exception as e:  # noqa: BLE001
        return None, e


def deployment(name: str, image: str, **extra) -> dict:
    """A one-replica Deployment, as the bot writes one; `extra` sets fields of the container or the metadata."""
    container = {"name": "app", "image": image}
    meta = {"name": name, "labels": {"app": name}}
    for k, v in extra.items():
        (meta if k in ("labels", "annotations") else container)[k] = v
    if "labels" in extra:
        meta["labels"] = {**extra["labels"], "app": name}
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": meta,
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}}, "spec": {"containers": [container]}}}}


# The stage's deploys, read where the KubeCon probe reads them but without importing the probe, which 30 tests already
# read: BurritoBot's game list in its own prompt (Challenge 2's images; c2-lands deploys the one /kubecon's C2 prompt
# names, Tron today), and HC-666's Joker under the stage's witch name on the internal registry's image (Challenge 3;
# c6-lands sends kubecon_probe.C6_MANIFEST, which joker_manifest() below writes in the same shape).
AGENT_PROMPT = REPO / "gitops/workshop-agent/agent.yaml"
GAMES_FROM, GAMES_TO = "use exactly its image below", "For any other app"
GAME_LINE = re.compile(r"^\s*-\s+([^:\n]+?):\s+(\S+@sha256:[0-9a-f]{64})\s*$", re.M)


def bot_game_images() -> dict[str, str]:
    text = AGENT_PROMPT.read_text(encoding="utf-8")
    if GAMES_FROM not in text or GAMES_TO not in text.split(GAMES_FROM, 1)[1]:
        raise SystemExit(f"{AGENT_PROMPT.relative_to(REPO)}: no game list between {GAMES_FROM!r} and {GAMES_TO!r}, "
                         "which this test reads the stage's images off")
    return {m.group(1).strip(): m.group(2)
            for m in GAME_LINE.finditer(text.split(GAMES_FROM, 1)[1].split(GAMES_TO, 1)[0])}


def joker_manifest(name: str) -> dict:
    """HC-666's Joker as the KubeCon probe's c6-lands sends it (kubecon_probe.C6_MANIFEST), under the given name."""
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": name, "namespace": "agent", "labels": {"app": name}},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}},
                                  "spec": {"containers": [{
                                      "name": "joker", "image": desk.ROOM_IMAGE,
                                      "resources": {"requests": {"cpu": "10m", "memory": "32Mi"},
                                                    "limits": {"cpu": "100m", "memory": "64Mi"}}}]}}}}


GAMES = bot_game_images()
if "Tron" not in GAMES:
    raise SystemExit(f"{AGENT_PROMPT.relative_to(REPO)}: no Tron in BurritoBot's game list {sorted(GAMES)}, the image "
                     "Challenge 2's ask deploys and this test builds its cases on")
GOOD_IMAGE = C2_IMAGE = GAMES["Tron"]
STAGE_NAME = desk.NAME_SPACE[0]
ROOM_JOKER = f"joker-{desk.slug(STAGE_NAME)}"


def word(term: str) -> str:
    """The term as one name-shaped word: a phrase's spaces become dashes, which the floor reads as a separator."""
    return term.replace(" ", "-")


def json_escaped_name(term: str) -> str:
    """A JSON manifest whose name spells the term's first letter as a \\u escape, so the text as sent shows no term and
    only the parsed string does."""
    raw = json.dumps(deployment("joker-placeholder", GOOD_IMAGE))
    first = word(term)[0]
    return raw.replace('"name": "joker-placeholder"', '"name": "joker-\\u%04x%s"' % (ord(first), word(term)[1:]), 1)


FIELDS = {
    "metadata.name": lambda t: (json.dumps(deployment(f"joker-{word(t)}", GOOD_IMAGE)), ""),
    "a label key": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE, labels={f"team/{word(t)}": "x"})), ""),
    "a label value": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE, labels={"team": word(t)})), ""),
    "an annotation": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE, annotations={"note": f"for the {t} crew"})),
                                ""),
    "the image": lambda t: (json.dumps(deployment("tron", f"ghcr.io/{word(t)}/tron:1.0")), ""),
    "an env value": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE, env=[{"name": "GREETING", "value": t}])), ""),
    "args": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE, args=["--motd", f"hello {t}"])), ""),
    "the command": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE, command=["sh", "-c", f"echo {t}"])), ""),
    "requested_by, the argument": lambda t: (json.dumps(deployment("tron", GOOD_IMAGE)), f"{t} the Kelpie"),
    "requested_by, written into the manifest": lambda t: (
        json.dumps({**deployment("tron", GOOD_IMAGE), "requested_by": f"{t} the Kelpie"}), ""),
    "a YAML manifest's name": lambda t: (
        f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: joker-{word(t)}\nspec:\n  replicas: 1\n"
        f"  selector:\n    matchLabels: {{app: x}}\n  template:\n    metadata:\n      labels: {{app: x}}\n"
        f"    spec:\n      containers:\n      - {{name: app, image: '{GOOD_IMAGE}'}}\n", ""),
    "a JSON \\u escape in the name": lambda t: (json_escaped_name(t), ""),
    "a manifest that does not parse": lambda t: ('{"apiVersion": "apps/v1" "kind": "Deployment", '
                                                 f'"metadata": {{"name": "joker-{word(t)}"}}}}', ""),
    "a bare name": lambda t: (json.dumps(f"joker {t}"), ""),
}

print("== deploy_app refuses a term anywhere in the deploy, for every term ==")
for field, make in FIELDS.items():
    bad: list[str] = []
    for i, term in enumerate(TERMS):
        manifest, requested_by = make(term)
        before = (len(applied), len(reports))
        result, exc = call(manifest, requested_by)
        msg = str(exc or "")
        why = ""
        if result is not None or not isinstance(exc, RuntimeError):
            why = "not refused"
        elif not msg.startswith("deploy failed for this manifest: ") or "code of conduct" not in msg \
                or not msg.endswith("Nothing was deployed."):
            why = "refused, but not for the code of conduct"
        elif FLOOR.spans(msg):
            why = "the refusal names the term"
        elif (len(applied), len(reports)) != before:
            why = "something was applied or reported"
        if why:
            bad.append(f"term {i}: {why}")
    check(f"{field}: refused for each of the {len(TERMS)} terms, plainly, naming none, applying and reporting nothing",
          not bad, "; ".join(bad[:5]))

_raw = json_escaped_name(TERMS[0])
check("the \\u escape case shows no term in the text as sent, so only the parsed strings' check can refuse it",
      not FLOOR.spans(_raw) and FLOOR.spans(json.loads(_raw)["metadata"]["name"]))
_, _exc = call(FIELDS["metadata.name"](TERMS[0])[0])
_msg = str(_exc)
check("the refusal reads as one plain instruction to tell the person, with no term and no manifest in it",
      "Tell the person that plainly" in _msg and "joker-" not in _msg and not FLOOR.spans(_msg), _msg)
check("the refusal starts 'deploy failed for ', which the collector marks a tool span ERROR on",
      _msg.startswith("deploy failed for ")
      and "deploy failed for " in (REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8"))

print("== deploy_app still deploys every stage image and Joker name ==")


def lands(manifest: str, requested_by: str, name: str, image: str) -> str:
    """Why this deploy did not land as the stage needs it, or "" when it did."""
    before = len(applied)
    result, exc = call(manifest, requested_by)
    if exc is not None:
        return f"refused: {str(exc)[:160]}"
    if not str(result).startswith("deployed "):
        return f"answered {result!r}"
    new = applied[before:]
    if len(new) != 1 or new[0]["obj"]["metadata"]["name"] != name:
        return f"applied {[a['obj']['metadata']['name'] for a in new]}"
    if server._first_image(new[0]["obj"]) != image:
        return f"applied image {server._first_image(new[0]['obj'])}"
    if not reports or reports[-1]["name"] != name or not reports[-1]["ok"] or reports[-1]["requested_by"] != requested_by:
        return f"reported {reports[-1] if reports else None}"
    return ""


def app_name(game: str) -> str:
    """The Deployment name the bot gives a game: its name in lower case, a space as a dash ("tron")."""
    return "-".join(game.lower().split())


_bad = {g: why for g, image in GAMES.items()
        if (why := lands(json.dumps(deployment(app_name(g), image)), STAGE_NAME, app_name(g), image))}
check(f"every game image BurritoBot's prompt deploys lands, credited to the stage's witch ({len(GAMES)})", not _bad,
      str(_bad))
_why = lands(json.dumps(joker_manifest(ROOM_JOKER)), STAGE_NAME, ROOM_JOKER, desk.ROOM_IMAGE)
check(f"the KubeCon probe's c6-lands manifest lands {ROOM_JOKER}, credited to {STAGE_NAME}", not _why, _why)
_bad = {}
for witch in desk.NAME_SPACE:
    joker = f"joker-{desk.slug(witch)}"
    _why = lands(json.dumps(joker_manifest(joker)), witch, joker, desk.ROOM_IMAGE)
    if _why:
        _bad[witch] = _why
check(f"a Joker for every one of the {len(desk.NAME_SPACE)} witch names lands, credited to its witch", not _bad,
      str(dict(list(_bad.items())[:3])))

# --- record_landing -------------------------------------------------------------------------------------------------
print("== record_landing stores no term, through /landed and the desk-relay's /remote-landed ==")
desk.REMOTE_TOKEN = "deploy-coc-test-token"


class _Desk:
    """The desk's own request handler with no socket: _landed is what /landed and /remote-landed both run."""

    def __init__(self):
        self.sent: list = []

    def _send(self, code, body):
        self.sent.append((code, body))


def landed(report: dict, remote: bool) -> dict:
    h = _Desk()
    desk.Handler._landed(h, json.dumps(report).encode(), desk.REMOTE_CLUSTER if remote else None)
    code, row = h.sent[-1]
    if code != 200:
        raise SystemExit(f"the desk's _landed answered {code}: {row}")
    return row


ROW_FIELDS = ("name", "kind", "image", "witch", "who", "detail")
_bad = []
for i, term in enumerate(TERMS):
    w = word(term)
    for remote in (False, True):
        for ok in (True, False):
            row = landed({"name": f"joker-{w}", "ok": ok, "kind": f"Kind-{w}", "image": f"ghcr.io/{w}/app:{w}",
                          "requested_by": f"{term} the Kelpie",
                          "detail": f'HTTP 403: admission webhook denied: Policy {w.lower()} failed: {term}'}, remote)
            hit = [f for f in ROW_FIELDS if FLOOR.spans(str(row.get(f, "")))]
            if hit:
                _bad.append(f"term {i} ({'remote' if remote else 'local'}, ok={ok}): {hit}")
check(f"no row stores a term in {', '.join(ROW_FIELDS)}, for each of the {len(TERMS)} terms, local and remote",
      not _bad, "; ".join(_bad[:5]))
_page = json.dumps(desk.deployments())
check("the deployments page's JSON carries no term", not FLOOR.spans(_page))
check("a masked name keeps what is not a term: joker-[redacted]",
      landed({"name": f"joker-{word(TERMS[0])}", "ok": True, "image": GOOD_IMAGE}, False)["name"] == "joker-[redacted]")

desk.LANDINGS.clear()
_bad = []
for witch in desk.NAME_SPACE:
    joker = f"joker-{desk.slug(witch)}"
    row = desk.record_landing(joker, True, "", desk.ROOM_IMAGE, witch, "Deployment")
    if (row["name"], row["witch"], row["who"], row["image"]) != (joker, witch, witch, desk.ROOM_IMAGE):
        _bad.append(witch)
check(f"every one of the {len(desk.NAME_SPACE)} witch names' Joker rows is stored unchanged", not _bad, str(_bad[:3]))
row = desk.record_landing("tron", True, "", C2_IMAGE, STAGE_NAME, "Deployment")
check("Challenge 2's row is stored unchanged, its image's short name what c2-lands reads",
      (row["name"], row["image"], row["witch"]) == ("tron", C2_IMAGE, STAGE_NAME)
      and desk.deployments()[0]["app"] == desk.image_label(C2_IMAGE))

print("== a cluster read and /desk-forget still find a masked row ==")
desk.LANDINGS.clear()
real = f"joker-{word(TERMS[0])}"
row = desk.record_landing(real, True, "", GOOD_IMAGE, "", "Deployment")
read = desk.record_cluster_read({"taken_at": row["ts"] + 1, "ok": True, "kinds": {"Deployment": [real, "tron"]}})
check("a read that lists the real name leaves the masked row running", read["marked"] == [] and not row["removed_at"],
      str(read))
read = desk.record_cluster_read({"taken_at": row["ts"] + 2, "ok": True, "kinds": {"Deployment": ["tron"]}})
check("a read that no longer lists it marks it removed, under its masked name",
      read["marked"] == ["joker-[redacted]"] and row["removed_at"], str(read))
desk.record_landing(real, True, "", GOOD_IMAGE, "", "Deployment")
gone = desk.forget_on_desk([real], 0.0)
check("/desk-forget given the real name removes the masked rows", gone["rows_removed"] == 2 and not desk.LANDINGS,
      str(gone))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("deploy_app refuses a code-of-conduct term anywhere in a deploy, the desk stores none, and the stage still lands.")
