# ABOUTME: Live check of #746's criterion in Whitney's Datadog sandbox org (#757): every recent BurritoBot interaction in
# ABOUTME: LLM Observability is one root-level row, and that row does not read "No content". Read-only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, and a KubeCon cluster shipping with a recent /chat)
"""The live half of #757. The offline halves are test_trace_shape_e2e.py, which builds the rows Datadog makes from what
the collector sends both intakes, and test_llmobs_view.py, which holds the judge and this file's logic.

It reads what Agent Observability shows: the LLM Observability export API's spans under ml_app burritobot over the
last WIB_DD_LOOKBACK_MIN minutes (default 60), GET /api/v2/llm-obs/v1/spans/events with filter[ml_app], filter[from]
and filter[to] as date math, page[limit] up to 5000 and the page[cursor] meta.page.after hands back
(docs.datadoghq.com/llm_observability/evaluations/export_api, read 2026-11-01). The spans are grouped by trace id, one
group per interaction, and llmobs_view.problems judges each: exactly one root-level row, a parent_id of "undefined"
or one that names no span of the interaction, and that row with an input and an output. #746's evidence trace
c943363f5467508c8bfc14c6a40c4b59 fails both: guard-proxy's POST /chat and kagent's empty workflow POST / are its roots.

The keys are watch-it-burn/datadog's (fleet_monitors.read_keys), as test_datadog_sandbox_live.py reads them:
WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2), never the ambient AWS default. Nothing
skips: no AWS, no key, a refused query or no interaction in the window is a FAIL with the reason. A trace from before
a cluster synced #746's change is in the window too and fails, so drive one /chat after the collector pods roll and
run it with a window that starts after that.
"""
from __future__ import annotations

import os
import pathlib
import sys
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
sys.path.insert(0, str(REPO / "verify"))
import fleet_monitors as fm  # noqa: E402
import llmobs_view as view  # noqa: E402

ML_APP = "burritobot"
PAGE = 5000
MAX_PAGES = 20


def spans(dd, minutes: int) -> list[dict]:
    """Every LLM Observability span under ML_APP in the window, every page of it."""
    out: list[dict] = []
    cursor = None
    for _ in range(MAX_PAGES):
        params = {"filter[ml_app]": ML_APP, "filter[from]": f"now-{minutes}m", "filter[to]": "now",
                  "page[limit]": PAGE}
        if cursor:
            params["page[cursor]"] = cursor
        got = dd.call("GET", "/api/v2/llm-obs/v1/spans/events?" + urllib.parse.urlencode(params))
        out += got.get("data") or []
        cursor = ((got.get("meta") or {}).get("page") or {}).get("after")
        if not cursor:
            return out
    raise RuntimeError(f"more than {MAX_PAGES * PAGE} spans under ml_app {ML_APP}; shorten WIB_DD_LOOKBACK_MIN")


def run(dd, minutes: int = 60, say=print) -> list[str]:
    """Every interaction as a check; returns the names of the ones that failed."""
    failures: list[str] = []

    def check(name: str, cond: bool, bad: list | None = None) -> None:
        say(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures.append(name)
            for line in (bad or [])[:20]:
                say(f"        {line}")

    say(f"== LLM Observability under ml_app {ML_APP}, the last {minutes} minutes (export API) ==")
    turns = view.interactions(view.from_export(spans(dd, minutes)))
    check(f"at least one BurritoBot interaction in the last {minutes} minutes", bool(turns),
          ["drive one /chat on a cluster shipping to this org, then run again"])
    for trace, rows in sorted(turns.items()):
        found = view.problems(rows)
        check(f"interaction {trace}: one root row, with the prompt and the reply ({len(rows)} rows)", not found, found)
    return failures


def main() -> int:
    profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
    region = os.environ.get("WIB_REGION", "us-west-2")
    minutes = int(os.environ.get("WIB_DD_LOOKBACK_MIN", "60"))
    try:
        api, app, site = fm.read_keys(profile, region)
        dd = fm.Datadog(site, api, app)
        print(f"== Whitney's sandbox org: {fm.org_name(dd)} ({site}), keys from {fm.SECRET_ID} as {profile} in {region} ==")
        failures = run(dd, minutes)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if failures:
        print(f"\nFAILED: {len(failures)} check(s). LLM Observability does not show each interaction as one root row "
              "with content (#746).")
        return 1
    print("\nEvery BurritoBot interaction is one root row with the prompt and the reply (#746).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
