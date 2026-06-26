# ABOUTME: Pytest suite for the Watch It Burn credential distribution app (v2).
# ABOUTME: Covers the EKS/console claim path, console + Datadog + AWS credential delivery, admin, healthz.

import csv

import pytest

import app as app_module

HEADER = [
    "name", "region", "access_key", "secret_key", "console_url",
    "datadog_org", "datadog_email", "datadog_password",
    "datadog_api_key", "datadog_app_key", "datadog_site", "datadog_dashboard_url",
]


def _row(n):
    return [
        f"test-cluster-0{n}", "us-west-2", f"AKIATESTKEY0{n}", f"secret0{n}",
        f"https://a-00{n}.agenticburn.com",
        f"wib-00{n}-LMS", f"dd00{n}@ddtraining.example.com", f"FAKE-pw-00{n}",
        f"ddapikey0000000000000000000000{n}", f"ddappkey000000000000000000000000000000{n}",
        "datadoghq.com", f"https://app.datadoghq.com/dashboard/EX-00{n}",
    ]


def _write_pool_csv(path, n_rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for i in range(1, n_rows + 1):
            writer.writerow(_row(i))


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "pool.db"
    csv_path = tmp_path / "pool.csv"
    _write_pool_csv(csv_path, 3)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    flask_app = app_module.create_app(
        database_path=str(db_path), pool_csv=str(csv_path), resend_api_key="",
    )
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.data == b"ok"


def test_claim_happy_path_delivers_full_credential_set(client):
    # POST /claim is preserved as a back-compat alias for POST /eks-claim.
    res = client.post("/claim", data={"email": "alice@example.com"})
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    # cluster + AWS
    assert "test-cluster-01" in body
    assert "AKIATESTKEY01" in body and "secret01" in body
    assert "aws eks update-kubeconfig --name test-cluster-01" in body
    # console URL (primary) + Datadog (dashboard, login, keys)
    assert "https://a-001.agenticburn.com" in body
    assert "https://app.datadoghq.com/dashboard/EX-001" in body
    assert "dd001@ddtraining.example.com" in body and "FAKE-pw-001" in body
    assert _row(1)[8] in body  # datadog_api_key renders
    assert _row(1)[9] in body  # datadog_app_key renders


def test_no_stale_kcd_or_kodekloud_content(client):
    body = client.post("/eks-claim", data={"email": "a@example.com"}).get_data(as_text=True)
    for stale in ["KCD_Texas", "KodeKloud", "kodekloud", "spec/BUILD-SPEC.md", "git clone"]:
        assert stale not in body, f"stale content still present: {stale}"


def test_reclaim_same_email_returns_same_cluster(client):
    first = client.post("/eks-claim", data={"email": "alice@example.com"})
    second = client.post("/eks-claim", data={"email": "alice@example.com"})
    third = client.post("/eks-claim", data={"email": "ALICE@example.com"})
    for r in (first, second, third):
        assert r.status_code == 200
        assert "test-cluster-01" in r.get_data(as_text=True)
    assert "test-cluster-02" not in second.get_data(as_text=True)


def test_second_email_gets_different_cluster(client):
    a = client.post("/eks-claim", data={"email": "alice@example.com"})
    b = client.post("/eks-claim", data={"email": "bob@example.com"})
    assert "test-cluster-01" in a.get_data(as_text=True)
    assert "test-cluster-02" in b.get_data(as_text=True)
    assert "https://a-002.agenticburn.com" in b.get_data(as_text=True)


def test_pool_exhausted_renders_exhausted_page(client):
    for i in range(3):
        assert client.post("/eks-claim", data={"email": f"user{i}@example.com"}).status_code == 200
    overflow = client.post("/eks-claim", data={"email": "late@example.com"})
    assert overflow.status_code == 200
    assert "All clusters claimed" in overflow.get_data(as_text=True)
    # Existing claimant can still re-display even when the pool is exhausted.
    reclaim = client.post("/eks-claim", data={"email": "user0@example.com"})
    assert reclaim.status_code == 200
    assert "test-cluster-01" in reclaim.get_data(as_text=True)


def test_invalid_email_rejected(client):
    res = client.post("/eks-claim", data={"email": "not-an-email"})
    assert res.status_code == 400


def test_root_is_the_claim_form(client):
    body = client.get("/").get_data(as_text=True)
    assert 'name="email"' in body
    assert 'action="/eks-claim"' in body
    assert "KodeKloud" not in body
    assert 'href="/browser"' not in body


def test_eks_form_url_redirects_to_root(client):
    res = client.get("/eks")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")


def test_browser_path_is_gone(client):
    # The KodeKloud /browser path was removed (Watch It Burn is EKS-only).
    assert client.get("/browser").status_code == 404
    assert client.post("/browser-claim", data={"email": "kk@example.com"}).status_code in (404, 405)


def test_admin_auth_and_no_browser_stats(client):
    assert client.get("/admin").status_code == 403
    assert client.get("/admin?token=wrong").status_code == 403
    ok = client.get("/admin?token=test-admin-token")
    assert ok.status_code == 200
    body = ok.get_data(as_text=True)
    assert "Total" in body and "Claimed" in body
    assert "Browser" not in body  # browser/KodeKloud stats removed


def test_admin_export_includes_console_and_datadog_columns(client):
    client.post("/eks-claim", data={"email": "alice@example.com"})
    res = client.get("/admin/export?token=test-admin-token")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "console_url" in body and "datadog_org" in body
    assert "alice@example.com" in body and "https://a-001.agenticburn.com" in body


def test_pool_with_blank_optional_fields_still_works(tmp_path, monkeypatch):
    # A pool row with only AWS fields (no console/datadog) must still claim cleanly.
    csv_path = tmp_path / "pool.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerow(["c1", "us-west-2", "AKIA1", "s1", "", "", "", "", "", "", "", ""])
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    flask_app = app_module.create_app(database_path=str(tmp_path / "p.db"),
                                      pool_csv=str(csv_path), resend_api_key="")
    with flask_app.test_client() as c:
        body = c.post("/eks-claim", data={"email": "x@example.com"}).get_data(as_text=True)
        assert "c1" in body and "AKIA1" in body
        assert "Open your console" not in body  # console section omitted when no URL


def test_admin_email_gets_instructor_bundle(client):
    # An admin email returns the admin cluster bundle (the four whitney-* clusters), not a pool row.
    res = client.post("/eks-claim", data={"email": "wiggitywhitney@gmail.com"})
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "watch-it-burn-whitney-r1" in body and "watch-it-burn-whitney-attendee" in body
    assert body.count("aws eks update-kubeconfig") == 4


def test_admin_email_is_case_insensitive(client):
    res = client.post("/eks-claim", data={"email": "MichaelRishiForrester@gmail.com"})
    assert res.status_code == 200
    assert "Instructor access" in res.get_data(as_text=True)


def test_admin_email_does_not_consume_the_attendee_pool(client):
    # Admin claim must not take a pool row: a normal attendee still gets the first seeded cluster.
    client.post("/eks-claim", data={"email": "wiggitywhitney@gmail.com"})
    res = client.post("/eks-claim", data={"email": "attendee1@example.com"})
    assert res.status_code == 200
    assert "test-cluster-01" in res.get_data(as_text=True)
