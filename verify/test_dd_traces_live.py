# ABOUTME: Live check of #759: the newest ml_app:burritobot trace is readable from Whitney's sandbox org with the
# ABOUTME: new read-only key, through hecaton's sources verb (a dispatched run) or the env pair (a session). Read-only.
# SUITE: e2e (needs WIB_DD_TRACES_VIA, the read-only key #759 created, and a BurritoBot /chat in the last day)
"""The live half of #759. The offline half is test_dd_traces.py.

WIB_DD_TRACES_VIA says how the key is reached, as dd_traces.py's --via: `sources` in a dispatched run, `env` in a
session that holds WIB_DD_TRACES_API_KEY and WIB_DD_TRACES_APP_KEY. There is no default, so a run that cannot reach
the key fails here and says why, instead of reading nothing. WIB_DD_TRACES_MINUTES (default 1440) is the window:
drive one /chat on either KubeCon cluster within it first.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dd_traces  # noqa: E402

via = os.environ.get("WIB_DD_TRACES_VIA", "")
if via not in ("sources", "env"):
    print("FAIL: set WIB_DD_TRACES_VIA to sources (a dispatched run, through hecaton's `sources datadog` verb) or env\n"
          f"      (a session holding {dd_traces.API_KEY_ENV} and {dd_traces.APP_KEY_ENV}); it is '{via}'",
          file=sys.stderr)
    sys.exit(1)
minutes = os.environ.get("WIB_DD_TRACES_MINUTES", "1440")
print(f"== the newest ml_app:{dd_traces.ML_APP} trace in the sandbox org, via {via}, last {minutes} minutes ==")
rc = dd_traces.main(["--via", via, "--minutes", minutes, "--traces", "1", "--apm"])
if rc != 0:
    print("FAIL: no BurritoBot trace could be read from the sandbox org (reason above)", file=sys.stderr)
    sys.exit(1)
print("A BurritoBot trace was read from the sandbox org with the read-only key.")
