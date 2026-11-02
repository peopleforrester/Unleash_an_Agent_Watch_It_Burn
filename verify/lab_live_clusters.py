# ABOUTME: Which clusters test_lab_pipeline_live.py may run against (#587): an attendee cluster, or one of the two
# ABOUTME: instructor-roster clusters (Community, private) whose own Datadog key is the instructor org's.
"""Both kinds ship the lab markers to the instructor org; they differ in what harvest pass 6 does with them.

An attendee cluster (watch-it-burn-attendee-NNN, Datadog name burritobot-attendee-NNN, #629) gets a lab-progress.csv
row. The Community and private clusters (burritobot-public, burritobot-private, and their -bNN build slots) take
fleet.sh datadog_keys_for's instructor path: their datadog-secret is the instructor org's key and they carry no
datadog-admin-secret, so the markers arrive there once. Pass 6 leaves them out of its rows by design (its
STUDENT_CLUSTER), because the room shares the Community cluster and an admin cluster's lab reports itself as a
student. The names are the ones infra/datadog-cluster-identity.sh derives; verify/test_lab_live_clusters.py holds
this module to that script.
"""
from __future__ import annotations

import re

ATTENDEE_EKS = re.compile(r"^watch-it-burn-attendee-\d+$")
ATTENDEE_DD = re.compile(r"^burritobot-attendee-\d+$")
INSTRUCTOR_EKS = {"burritobot-public": re.compile(r"^watch-it-burn-community(-b\d\d)?$"),
                  "burritobot-private": re.compile(r"^watch-it-burn-private(-b\d\d)?$")}


def kind(eks: str, dd: str) -> str:
    """"attendee", "instructor", or "" when the pair is neither (the check then refuses the cluster)."""
    if ATTENDEE_EKS.fullmatch(eks) and ATTENDEE_DD.fullmatch(dd) and eks.rsplit("-", 1)[1] == dd.rsplit("-", 1)[1]:
        return "attendee"
    if dd in INSTRUCTOR_EKS and INSTRUCTOR_EKS[dd].fullmatch(eks):
        return "instructor"
    return ""
