# ABOUTME: Finds the image a Dockerfile's FROM lines pull, the way llm-coding-workflow's mirror-images.sh does.
# ABOUTME: Shared by test_images_lock.py (every reference has a row) and test_no_docker_hub.py (none is Docker Hub's).
from __future__ import annotations

import re


def from_refs(text: str):
    """FROM lines: flags skipped, scratch and an earlier AS stage of the same file are not pulls."""
    stages: set[str] = set()
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\r").lstrip(" \t")
        if line[:4].lower() != "from" or line[4:5] not in (" ", "\t"):
            continue
        t = re.split(r"[ \t]+", line)
        i = 1
        while i < len(t) and t[i].startswith("--"):
            i += 1
        if i >= len(t):
            continue
        img = t[i]
        if img.lower() != "scratch" and img.lower() not in stages:
            yield n, img
        if i + 2 < len(t) and t[i + 1].lower() == "as":
            stages.add(t[i + 2].lower())
