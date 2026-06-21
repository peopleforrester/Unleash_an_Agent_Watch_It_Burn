# ABOUTME: Pytest suite for the Watch It Burn credential distribution app.
# ABOUTME: Covers picker, browser path, EKS path (incl. back-compat /claim), admin, healthz.

import csv

import pytest

import app as app_module


def _write_pool_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "access_key", "secret_key", "region"])
        for row in rows:
            writer.writerow(row)


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "pool.db"
    csv_path = tmp_path / "pool.csv"
    _write_pool_csv(
        csv_path,
        [
            ("test-cluster-01", "AKIATESTKEY01", "secret01", "us-west-2"),
            ("test-cluster-02", "AKIATESTKEY02", "secret02", "us-west-2"),
            ("test-cluster-03", "AKIATESTKEY03", "secret03", "us-west-2"),
        ],
    )
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    flask_app = app_module.create_app(
        database_path=str(db_path),
        pool_csv=str(csv_path),
        resend_api_key="",
    )
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ---------- existing surface ---------------------------------------------------

def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.data == b"ok"


def test_claim_happy_path(client):
    # POST /claim is preserved as a back-compat alias for POST /eks-claim.
    res = client.post("/claim", data={"email": "alice@example.com"})
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "test-cluster-01" in body
    assert "AKIATESTKEY01" in body
    assert "secret01" in body
    assert "us-west-2" in body
    assert "aws eks update-kubeconfig --name test-cluster-01" in body


def test_reclaim_same_email_returns_same_cluster(client):
    first = client.post("/eks-claim", data={"email": "alice@example.com"})
    second = client.post("/eks-claim", data={"email": "alice@example.com"})
    third = client.post("/eks-claim", data={"email": "ALICE@example.com"})
    for r in (first, second, third):
        assert r.status_code == 200
        assert "test-cluster-01" in r.get_data(as_text=True)
    assert "AKIATESTKEY01" in second.get_data(as_text=True)
    assert "test-cluster-02" not in second.get_data(as_text=True)


def test_second_email_gets_different_cluster(client):
    a = client.post("/eks-claim", data={"email": "alice@example.com"})
    b = client.post("/eks-claim", data={"email": "bob@example.com"})
    assert "test-cluster-01" in a.get_data(as_text=True)
    assert "test-cluster-02" in b.get_data(as_text=True)
    assert "AKIATESTKEY02" in b.get_data(as_text=True)


def test_eks_pool_exhausted_renders_exhausted_page(client):
    for i in range(3):
        assert client.post("/eks-claim", data={"email": f"user{i}@example.com"}).status_code == 200
    overflow = client.post("/eks-claim", data={"email": "late@example.com"})
    assert overflow.status_code == 200
    body = overflow.get_data(as_text=True)
    assert "All clusters claimed" in body
    assert "the workshop host" in body  # parameterized host name (WORKSHOP_HOST default)
    # Existing claimant can still re-display even when pool is exhausted.
    reclaim = client.post("/eks-claim", data={"email": "user0@example.com"})
    assert reclaim.status_code == 200
    assert "test-cluster-01" in reclaim.get_data(as_text=True)


def test_admin_auth(client):
    assert client.get("/admin").status_code == 403
    assert client.get("/admin?token=wrong").status_code == 403
    ok = client.get("/admin?token=test-admin-token")
    assert ok.status_code == 200
    body = ok.get_data(as_text=True)
    assert "Total" in body
    assert "Claimed" in body


# ---------- new two-path surface ----------------------------------------------

def test_root_is_the_eks_form(client):
    # The picker page was merged into the form. `/` should serve the form
    # itself - Accenture sponsor strip + email input + submit button - with
    # zero intermediate clicks.
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Accenture" in body
    assert "accenture-logo.svg" in body
    assert 'name="email"' in body                     # form input present
    assert 'action="/eks-claim"' in body              # posts directly to claim endpoint
    assert "Claim my cluster" in body                 # CTA copy
    # KodeKloud is hidden from the root, but the /browser route still works.
    assert "KodeKloud" not in body
    assert 'href="/browser"' not in body


def test_eks_form_url_redirects_to_root(client):
    # Back-compat: any QR codes or shared links to /eks still land users in
    # the right place via a 302 to /.
    res = client.get("/eks")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")


def test_browser_route_still_works_off_menu(client):
    # KodeKloud was removed from the picker but the route is intentionally
    # preserved so anyone with a direct link can still register.
    assert client.get("/browser").status_code == 200
    assert client.post("/browser-claim", data={"email": "kk@example.com"}).status_code == 200


def test_browser_claim_happy_path(client):
    res = client.post("/browser-claim", data={"email": "carol@example.com"})
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Open KodeKloud course" in body
    assert "learn.kodekloud.com/user/courses/unleash-an-agent-watch-it-burn" in body
    assert "kubectl get nodes" in body
    assert "git clone https://github.com/peopleforrester/KCD_Texas_2026_Workshop.git" in body


def test_browser_reclaim_is_idempotent(client):
    first = client.post("/browser-claim", data={"email": "dana@example.com"})
    second = client.post("/browser-claim", data={"email": "dana@example.com"})
    third = client.post("/browser-claim", data={"email": "DANA@example.com"})
    for r in (first, second, third):
        assert r.status_code == 200
    # Admin should show exactly one browser-claim row for dana despite 3 submits.
    admin = client.get("/admin?token=test-admin-token")
    body = admin.get_data(as_text=True)
    assert body.count("dana@example.com") == 1


def test_cross_path_note_appears(client):
    """Same email on both paths: each success page mentions the other record."""
    client.post("/eks-claim", data={"email": "ed@example.com"})
    browser_res = client.post("/browser-claim", data={"email": "ed@example.com"})
    browser_body = browser_res.get_data(as_text=True)
    assert "EKS terminal" in browser_body
    assert "test-cluster-01" in browser_body  # the cluster they hold

    eks_res = client.post("/eks-claim", data={"email": "ed@example.com"})
    eks_body = eks_res.get_data(as_text=True)
    assert "browser (KodeKloud)" in eks_body
