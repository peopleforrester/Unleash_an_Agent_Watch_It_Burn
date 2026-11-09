# ABOUTME: Offline half of #1166: holds verify/purge_647.py's verdicts on #647's post-talk purge to the lines
# ABOUTME: dd_purge_public.py really prints, and checks each verdict refuses a record or a run that falls short.
"""Nothing here reaches Datadog, AWS or GitHub.

#647's criterion (#1166): after the talk on 2026-11-12, the burritobot-public data (APM spans and Agent Observability
spans, including the scrub check's own wib-pii-scrub-check spans) is purged from Whitney's Datadog org, and the
result is posted on the issue. verify/test_dd_purge_public_live.py holds it on GitHub and in the org, with
verify/purge_647.py's two verdicts. This test holds those verdicts:

- The script's output is real: verify/dd_purge_public.py's `main` runs against a fake org (the four paths it asks,
  nothing else answered), so a reworded line in the script fails here, not on the day of the purge.
- A comment that pastes those lines passes `comment_verdict`, and each cut of it (no script, no --apply line, a
  window that starts late or ends before the talk ended, no Purged line, no wib-pii-scrub-check, no APM line, no
  word on how the APM spans go) is refused.
- `verify_verdict` passes a --verify run with nothing left, and fails one with an Agent Observability span left, one
  with APM spans left (APM has no delete API), and one under the wrong query.
- The live test uses both verdicts on #647, runs --verify on the comment's window and on wib-pii-scrub-check, and is
  in run-e2e.sh's suite but not the promotion gate's tools tier, since it is red until the purge after the talk.
- The run-of-show's Teardown purge step asks for the lines the comment verdict reads, and names the live test.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dd_purge_public as p  # noqa: E402
import purge_647 as purge  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal when a cut-anchor is not present, so a reworded line reads as that."""
    if literal not in text:
        sys.exit(f"test_purge_647_record.py: {where} no longer holds the literal {literal!r}; "
                 "reword the test's anchor to match")


ORG = "5a6c3583-157d-11f0-845c-2241f983918a"
SECRET = {"api-key": "API", "app-key": "READ", "write-app-key": "WRITE", "site": "datadoghq.com",
          "org": f"Datadog (Whitney Lee sandbox, {ORG})"}
FROM, TO = "2026-10-28", "2026-11-13T09:00:00Z"
T0 = p.ms("2026-11-12T21:00:00Z")


def span(n: int, ml_app: str = "burritobot") -> dict:
    return {"id": f"s{n}", "type": "span",
            "attributes": {"trace_id": f"{n:032x}", "ml_app": ml_app, "start_ns": (T0 + n * 1000) * 1_000_000}}


class Org:
    """A fake Datadog org answering the four paths dd_purge_public.py asks, with `spans` listed and `apm` counted."""

    def __init__(self, spans: list[dict], apm: int):
        self.spans, self.apm, self.calls = spans, apm, []

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        self.calls.append((method, u.path, headers.get("DD-APPLICATION-KEY"), json.loads(body) if body else None))
        if method == "GET" and u.path == p.ME_PATH:
            return 200, {"data": {}, "included": [{"type": "orgs", "attributes": {"public_id": ORG}}]}
        if method == "GET" and u.path == p.LLMOBS_SPANS:
            return 200, {"data": self.spans, "meta": {}}
        if method == "POST" and u.path == p.APM_AGGREGATE:
            return 200, {"data": [{"type": "bucket", "attributes": {"compute": {"c0": self.apm}}}]}
        if method == "POST" and u.path == p.DELETE_PATH:
            return 202, {"data": {"id": f"req-{len(self.calls)}", "type": "deletion_request"}}
        return 404, {"errors": ["Not found"]}


def run(args: list[str], org: Org) -> tuple[int, str]:
    out: list[str] = []
    rc = p.main(["--profile", "accen-dev", "--from", FROM, "--to", TO, *args], keys=lambda *_: dict(SECRET),
                http=org, say=out.append, sleep=lambda _s: None)
    return rc, "\n".join(out)


print("== dd_purge_public.py's real lines, from a fake org ==")
rc_apply, apply_out = run(["--apply"], Org([span(1), span(2), span(3, purge.CHECK_SERVICE)], 412))
check("--apply on three traces exits 0", rc_apply == 0, apply_out)
rc_v, verify_out = run(["--verify"], Org([], 412))
check("--verify with nothing left exits 0", rc_v == 0, verify_out)
rc_c, clean_out = run(["--verify"], Org([], 0))
rc_s, svc_out = run(["--verify", "--service", purge.CHECK_SERVICE], Org([], 0))
rc_l, left_out = run(["--verify"], Org([span(4, purge.CHECK_SERVICE)], 0))
check("--verify with a span left exits 1", rc_l == 1, left_out)

print("== a comment that pastes them passes comment_verdict ==")
BODY = f"""Purged #647's burritobot-public data from Whitney's sandbox org after the talk, with `{purge.SCRIPT}`.

`python3 verify/dd_purge_public.py --profile accen-dev --from {FROM} --to {TO} --apply`:
```
{apply_out}
```
`--verify`, eight minutes later (the room's bot and the scrub check's `{purge.CHECK_SERVICE}` spans alike):
```
{verify_out}
```
The APM spans have no delete API and are left to retention.
"""
ok, why = purge.comment_verdict(BODY)
check("the comment passes", ok, why)
check("its window is read back as the script printed it",
      purge.window(BODY) == ("2026-10-28T00:00:00+00:00", "2026-11-13T09:00:00+00:00", ORG), purge.window(BODY))
check("a comment wrapped and in backticks reads the same",
      purge.comment_verdict(BODY.replace("\n", "\n  ").replace("Purged: no", "`Purged:\nno"))[0])


def cut(old: str, new: str, count: int = -1) -> str:
    anchor(BODY, old, "the fixture comment")
    return BODY.replace(old, new, count)


def refused(name: str, body: str) -> None:
    ok_, why_ = purge.comment_verdict(body)
    check(name, not ok_, f"the verdict still held: {why_}")


print("== each cut of it is refused ==")
refused("with dd_purge_public.py unnamed, it is refused", cut(purge.SCRIPT, "the purge script"))
refused("with no --apply line, it is refused", cut("Sent 1 deletion requests", "Would send 1 deletion requests"))
refused("with a window that starts after the first build day, it is refused",
        cut("Window 2026-10-28T00:00:00+00:00", "Window 2026-11-01T00:00:00+00:00"))
refused("with a window that ends before the talk ended, it is refused",
        cut("to 2026-11-13T09:00:00+00:00, org", "to 2026-11-12T21:00:00+00:00, org"))
refused("with a window time that has no zone, it is refused",
        cut("to 2026-11-13T09:00:00+00:00, org", "to 2026-11-13T09:00:00, org"))
refused("with no Purged line, it is refused", cut(purge.PURGED, "Not purged yet: 1 Agent Observability spans are left."))
refused("with wib-pii-scrub-check unnamed, it is refused", cut(purge.CHECK_SERVICE, "the check's"))
refused("with no APM line, it is refused", cut("APM: 412 spans under", "APM spans under"))
refused("with no word on how the APM spans go, it is refused",
        cut("are left to retention", "stay").replace("retention or support", "later"))
anchor(verify_out, "retention or support", "dd_purge_public.py's --verify output")
check("the APM line itself says retention or support, which is why the last cut also takes it out",
      "retention or support" in verify_out)

print("== verify_verdict passes only a run with nothing left ==")


def verdict(out: str, rc: int, service: str | None = None) -> dict[str, bool]:
    return {name: ok_ for name, ok_, _ in purge.verify_verdict(out, rc, service)}


got = verdict(clean_out, rc_c)
check("a --verify with no span and no APM span left passes every check", all(got.values()) and len(got) == 4, got)
got = verdict(svc_out, rc_s, purge.CHECK_SERVICE)
check("the same narrowed to wib-pii-scrub-check passes every check", all(got.values()) and len(got) == 4, got)
got = verdict(verify_out, rc_v)
check("with APM spans left it fails only the APM check",
      [n for n, ok_ in got.items() if not ok_] == ["no APM span is left under kube_cluster_name:burritobot-public"],
      got)
got = verdict(left_out, rc_l)
check("with the check's span left it fails the exit, Purged and Agent Observability checks",
      sum(not ok_ for ok_ in got.values()) == 3 and got["no APM span is left under kube_cluster_name:burritobot-public"],
      got)
got = verdict(clean_out, rc_c, purge.CHECK_SERVICE)
check("an unnarrowed run read as the wib-pii-scrub-check run fails its span counts",
      sum(not ok_ for ok_ in got.values()) == 2, got)
check("an empty output fails every check", not any(verdict("", 1).values()))

print("== the live test holds #647 with both verdicts ==")
LIVE = HERE / "test_dd_purge_public_live.py"
src = LIVE.read_text(encoding="utf-8")
for need in ("purge.comment_verdict", "purge.verify_verdict", "gh_comments.read", '"--verify"',
             "purge.CHECK_SERVICE", "purge.window(", "p.org_id(secret)"):
    check(f"the live test uses {need}", need in src)
head = src.split('"""', 1)[0]
check("it is in run-e2e.sh's suite", "\n# SUITE: e2e" in "\n" + head)
check("it is not in the promotion gate's tools tier, since it is red until the purge after the talk",
      "# E2E TIER" not in head)
print("== the run-of-show's purge step asks for the lines the verdict reads ==")
SHOW = (HERE.parent / "facilitation" / "kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
step = purge.flat(next((b for b in SHOW.split("\n- ") if b.startswith("Purge the room's data")), ""))
check("the run-of-show has the Teardown purge step", bool(step))
for need in ("Sent", "Window", "APM", "Purged:", purge.CHECK_SERVICE, "verify/test_dd_purge_public_live.py", "#647"):
    check(f"the purge step names {need}", need in step)
check("the purge's issue is #647", purge.ISSUE.endswith("#647"))
check("the talk ends 2026-11-12T21:20Z, the 13:50 MST start and 30 minutes",
      purge.TALK_END.isoformat() == "2026-11-12T21:20:00+00:00")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#647's purge verdicts hold: they read dd_purge_public.py's own lines, and refuse a record or a run that falls "
      "short.")
