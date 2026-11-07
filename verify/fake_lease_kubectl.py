# ABOUTME: A fake kubectl for the guard lock's tests (#1024, #1016): it keeps the Lease agent/wib-guard-lock in a JSON file,
# ABOUTME: answers get, create, replace and precondition delete as the API server does, and names the guardrails peer.
"""The Lease half of the API server, for offline tests of verify/guard_lease.py and the scripts that take the lock.

In process, FakeLeaseApi(...).run is a runner with subprocess.run's shape, for GuardLease(runner=...). As a program,
`fake_lease_kubectl.py <kubectl args>` keeps its Lease in $FAKE_LEASE_STATE (a JSON file) and appends each call to
$FAKE_LEASE_LOG when set, so a shell test's fake kubectl can hand its Lease calls here. It also answers the one read
hold_switch makes (#1016), the `name` of guardrails-switch/guardrails-peer: `peer` in process, and in a program the
entry for the call's context in $FAKE_LEASE_PEERS (a JSON map of context to peer); no entry is no Secret. Any other
call exits 9 naming it, so a test never mistakes an unhandled call for an answered one.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys

NAME, NAMESPACE = "wib-guard-lock", "agent"
API_PATH = f"/apis/coordination.k8s.io/v1/namespaces/{NAMESPACE}/leases/{NAME}"
PEER_GET = ["-n", "guardrails-switch", "get", "secret", "guardrails-peer", "--ignore-not-found", "-o",
            "jsonpath={.data.name}"]


class FakeLeaseApi:
    def __init__(self, lease: dict | None = None, rv: int = 100, peer: str = "") -> None:
        self.lease = lease
        # The cluster this one's guardrails switch reaches, as the guardrails-peer Secret names it; "" is no Secret.
        self.peer = peer
        self.rv = rv
        self.calls: list[list[str]] = []
        # Names a verb whose next call answers Conflict, as if another holder wrote between our read and our write.
        self.conflict_next: str | None = None

    def _stamp(self, obj: dict) -> dict:
        self.rv += 1
        obj = json.loads(json.dumps(obj))
        obj.setdefault("metadata", {})["resourceVersion"] = str(self.rv)
        return obj

    def handle(self, argv: list[str], stdin: str | None) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        args = list(argv)
        if args[:1] == ["kubectl"]:
            args = args[1:]
        if args[:1] != ["--context"] or len(args) < 2 or not args[1]:
            return 9, "", f"fake kubectl: no explicit --context first: {argv}\n"
        args = args[2:]
        if args == PEER_GET:
            return 0, (base64.b64encode(self.peer.encode()).decode() if self.peer else ""), ""
        if args[:5] == ["-n", NAMESPACE, "get", "lease", NAME]:
            return 0, (json.dumps(self.lease) if self.lease else ""), ""
        if args[:3] == ["create", "-f", "-"]:
            if self.lease is not None:
                return 1, "", f'Error from server (AlreadyExists): leases.coordination.k8s.io "{NAME}" already exists\n'
            self.lease = self._stamp(json.loads(stdin or "{}"))
            return 0, json.dumps(self.lease), ""
        if args[:3] == ["replace", "-f", "-"]:
            if self.lease is None:
                return 1, "", f'Error from server (NotFound): leases.coordination.k8s.io "{NAME}" not found\n'
            new = json.loads(stdin or "{}")
            if self.conflict_next == "replace" or new["metadata"].get("resourceVersion") != \
                    self.lease["metadata"]["resourceVersion"]:
                self.conflict_next = None
                return 1, "", f'Error from server (Conflict): Operation cannot be fulfilled on leases "{NAME}"\n'
            self.lease = self._stamp(new)
            return 0, json.dumps(self.lease), ""
        if args[:4] == ["delete", "--raw", API_PATH, "-f"]:
            if self.lease is None:
                return 1, "", "Error from server (NotFound)\n"
            pre = (json.loads(stdin or "{}").get("preconditions") or {}).get("resourceVersion")
            if pre != self.lease["metadata"]["resourceVersion"]:
                return 1, "", "Error from server (Conflict): the ResourceVersion in the precondition does not match\n"
            self.lease = None
            return 0, '{"kind":"Status","status":"Success"}', ""
        return 9, "", f"fake kubectl: not a guard-lock call: {argv}\n"

    def run(self, argv, input=None, **_kw) -> subprocess.CompletedProcess:
        rc, out, err = self.handle(argv, input)
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


def main(argv: list[str]) -> int:
    state = pathlib.Path(os.environ["FAKE_LEASE_STATE"])
    saved = json.loads(state.read_text()) if state.exists() else {"lease": None, "rv": 100}
    peers = json.loads(os.environ.get("FAKE_LEASE_PEERS") or "{}")
    api = FakeLeaseApi(saved["lease"], saved["rv"], peers.get(argv[1] if len(argv) > 1 else "", ""))
    stdin = sys.stdin.read() if "-f" in argv and "-" in argv else None
    rc, out, err = api.handle(argv, stdin)
    state.write_text(json.dumps({"lease": api.lease, "rv": api.rv}))
    if os.environ.get("FAKE_LEASE_LOG"):
        with open(os.environ["FAKE_LEASE_LOG"], "a", encoding="utf-8") as f:
            f.write(" ".join(argv) + "\n")
    sys.stdout.write(out)
    sys.stderr.write(err)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
