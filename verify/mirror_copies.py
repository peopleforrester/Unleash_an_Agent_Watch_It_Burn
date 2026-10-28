# ABOUTME: lab-platform's deploy/mirror/copies.tsv as this repo uses it (#623): each Docker Hub image a chart here
# ABOUTME: pulls, its linux/amd64 digest, the mirror/ copy it is named by, and the app files that name the copy.
"""One table for the tests that ask where each mirror copy is named.

lab-platform copies each vendor image under ghcr.io/peopleforrester/lab-platform/mirror/, tagged with its upstream
tag and the first twelve characters of its linux/amd64 manifest digest, so the mirror only ever adds a tag. The
rows are the ones lab-platform#183 handed over on 2026-10-28 (Watch_It_Burn#623, comment 6474733299), every one
public. An app file names a copy as "{{ .Values.imageRegistry }}/<path>", which the root renders at the chart's
default, ghcr.io/peopleforrester/lab-platform, unless a value is passed.

UNPULLED are copies of a tag no chart here pulls any more. copies.tsv was resolved against this repo at 01c1d9e;
89fce6a then took Falco chart 9.2.1, which pulls falco 0.45.1 and falcoctl 0.14.2, so naming the 0.44.1 and
0.13.0 copies would downgrade Falco below the kernel 6.18 fix. Those two images stay on Docker Hub until
lab-platform copies the tags the chart pulls.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Copy:
    apps: tuple[str, ...]  # the gitops/bootstrap/apps/<name>.yaml files that name it
    upstream: str  # the reference the chart pulled before the copy
    digest: str  # its linux/amd64 manifest digest
    path: str  # the copy, under the registry

    @property
    def tag(self) -> str:
        return self.path.rsplit(":", 1)[1]


COLLECTORS = ("otel-collector", "otel-collector-attendee", "otel-collector-burn")

COPIES = (
    Copy(("falco-talon",), "falco.docker.scarf.sh/falcosecurity/falco-talon:0.3.0",
         "sha256:0a06b6a5e9f0e45d4ccdcf4c7a8c5ac4156e728f81ffd0122cb6675e3b525b40",
         "mirror/falcosecurity/falco-talon:0.3.0-0a06b6a5e9f0"),
    Copy(("falcosidekick",), "docker.io/falcosecurity/falcosidekick:2.32.0",
         "sha256:399d95934a67b1c6b57d3e1f678694b3407f89f878e8fd072dba51968fa9745f",
         "mirror/falcosecurity/falcosidekick:2.32.0-399d95934a67"),
    Copy(("kagent",), "docker.io/library/postgres:18.6-alpine3.23",
         "sha256:dd504ba15d335bb17f83ed48a75899501be82726126a691f597fb91e1e505373",
         "mirror/library/postgres:18.6-alpine3.23-dd504ba15d33"),
    Copy(("kagent",), "mcp/grafana:latest",
         "sha256:208f8ea16064060f92e9960b2f060f5e37af5abda3ec14c1a8ebbc4d5cc8c718",
         "mirror/mcp/grafana:latest-208f8ea16064"),
    # The operator's own image, the chart's; the other five are compiled into the operator.
    Copy(("kubearmor",), "docker.io/kubearmor/kubearmor-operator:v1.7.4",
         "sha256:84626528c4d6e6a11ba7082f0b87eb15bb73bb9b14b3b600a79f3c7dffe6e67a",
         "mirror/kubearmor/kubearmor-operator:v1.7.4-84626528c4d6"),
    Copy(("kubearmor",), "docker.io/kubearmor/kubearmor:stable",
         "sha256:bf867783eb30368db13e6244e5cf42689997406d7f4fc11ef06479154fe00388",
         "mirror/kubearmor/kubearmor:stable-bf867783eb30"),
    Copy(("kubearmor",), "docker.io/kubearmor/kubearmor-init:stable",
         "sha256:cdc3763f302de555cb093238bb4a7d93dee64423e96459318ebfbf94c018c22d",
         "mirror/kubearmor/kubearmor-init:stable-cdc3763f302d"),
    Copy(("kubearmor",), "docker.io/kubearmor/kubearmor-relay-server:latest",
         "sha256:e4fd875cc1e4f6f6a2a90c57655d3bda09fc7846eb82ea24e0296e578ee29f29",
         "mirror/kubearmor/kubearmor-relay-server:latest-e4fd875cc1e4"),
    Copy(("kubearmor",), "docker.io/kubearmor/kubearmor-controller:latest",
         "sha256:89f52a3e9fc07af532c68019c028451a5986a63d128dccb560bf3aa3004c8922",
         "mirror/kubearmor/kubearmor-controller:latest-89f52a3e9fc0"),
    Copy(("kubearmor",), "docker.io/kubearmor/kubearmor-snitch:latest",
         "sha256:ec11d33057b18aaec179aa32b8d689b8f732e422777df9c78d7ed5287cbf6e1a",
         "mirror/kubearmor/kubearmor-snitch:latest-ec11d33057b1"),
    Copy(COLLECTORS, "otel/opentelemetry-collector-contrib:0.160.0",
         "sha256:5b66b0dc6921f2a439cf50b942ccb9e2a4375f136239a9fdf709ef33e4bfc668",
         "mirror/otel/opentelemetry-collector-contrib:0.160.0-5b66b0dc6921"),
    Copy(("otel-operator",), "otel/opentelemetry-collector-k8s:0.158.0",
         "sha256:158b837a5e9828c8a6ca00e657e6fffd9b9b24e4a5f7862d0713505cd99c7b42",
         "mirror/otel/opentelemetry-collector-k8s:0.158.0-158b837a5e98"),
    Copy(("prometheus",), "docker.io/grafana/grafana:13.2.2-distroless",
         "sha256:ada1141b386c443192521bfed414c62209428361111f1505988930adf9dee751",
         "mirror/grafana/grafana:13.2.2-distroless-ada1141b386c"),
    Copy(("tempo",), "docker.io/grafana/tempo:3.0.3",
         "sha256:05321ebf1f191fde34282b3dc86e68f511d489133df7963cd1670a2e1e11b33c",
         "mirror/grafana/tempo:3.0.3-05321ebf1f19"),
)

UNPULLED = (
    Copy(("falco",), "docker.io/falcosecurity/falco:0.44.1",
         "sha256:9f02feb5544a54a4ca2974bd8ab3a0cca287f3fe7c697d612814357af0cc55e5",
         "mirror/falcosecurity/falco:0.44.1-9f02feb5544a"),
    Copy(("falco",), "docker.io/falcosecurity/falcoctl:0.13.0",
         "sha256:ffe71491ff79e5255d25ed627fffce0c7ce7beb7355dc2e507abefc791e13603",
         "mirror/falcosecurity/falcoctl:0.13.0-ffe71491ff79"),
)


def apps() -> list[str]:
    """Every app file that names a copy, once each, in table order."""
    return list(dict.fromkeys(a for c in COPIES for a in c.apps))
