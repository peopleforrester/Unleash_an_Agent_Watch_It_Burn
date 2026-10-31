# ABOUTME: lab-platform's web image as this repo pins it (#668): the digest, the five demo apps that run it, and the
# ABOUTME: fields lab-platform's web.yaml parser accepts. Shared by the offline gate and the tools-tier serve check.
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent

# web:v1 as lab-platform#55's umask-022 republish left it (lab-platform PR #336, built from 1a16639 on 2026-10-30).
# lab-platform#278 first published 74885296c746... from 3dd635a, the build #650 read; the republish moved the tag.
DIGEST = "sha256:73cd15652cb8b8eb706bd43f8877541db7f7c9e5f810ef0739636a27fc34fbd9"
GHCR = "ghcr.io/peopleforrester/lab-platform/web"
DEMO_APPS = ("hedgehog", "mantis-shrimp", "spider", "unicorn", "wombat")

# internal/webserve/config.go's field lists at lab-platform 1a16639: the parser refuses any other field, by line,
# and the pod exits at start.
TOP_FIELDS = {"listen", "tls", "root", "routes", "hosts"}
ROUTE_FIELDS = {"path", "prefix", "file", "status", "text", "text_host", "proxy", "host", "websocket",
                "accept_encoding", "timeout", "methods", "rate", "burst", "max_body", "content_type"}
HOST_FIELDS = {"match", "proxy", "fallback"}


def demo_dir(app: str) -> pathlib.Path:
    return REPO / f"gitops/manifests/demo-app-{app}"


def demo_docs(app: str) -> list[dict]:
    """The bundle's documents, read from the files its kustomization.yaml lists."""
    d = demo_dir(app)
    kust = yaml.safe_load((d / "kustomization.yaml").read_text(encoding="utf-8"))
    return [doc for f in kust["resources"] for doc in yaml.safe_load_all((d / f).read_text(encoding="utf-8")) if doc]


def demo_files(app: str) -> dict[str, str]:
    """The demo app's ConfigMap data: index.html and web.yaml."""
    cm = next(d for d in demo_docs(app) if d["kind"] == "ConfigMap")
    return dict(cm.get("data") or {})
