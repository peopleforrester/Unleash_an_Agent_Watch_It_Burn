# ABOUTME: Flask app that distributes pre-provisioned EKS cluster credentials to Watch It Burn
# ABOUTME: workshop attendees. Idempotent claim by email; optional Resend email delivery.

import csv
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

import requests
from flask import Flask, abort, g, redirect, render_template, request, url_for

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

RESEND_ENDPOINT = "https://api.resend.com/emails"
RESEND_FROM = "Watch It Burn Workshop <workshop@agenticburn.com>"
RESEND_SUBJECT_EKS = "Watch It Burn Workshop - Your EKS Cluster Credentials"
RESEND_SUBJECT_BROWSER = "Watch It Burn Workshop - Your KodeKloud Lab Info"
RESEND_TIMEOUT_SECONDS = 5

KODEKLOUD_COURSE_URL = "https://learn.kodekloud.com/user/courses/unleash-an-agent-watch-it-burn"


def _resolve_admin_token() -> str:
    token = os.environ.get("ADMIN_TOKEN")
    if token:
        return token
    generated = secrets.token_urlsafe(32)
    print(f"[startup] ADMIN_TOKEN not set; using generated token: {generated}", flush=True)
    return generated


def _build_commands_block(cluster_name, region):
    return (
        f"aws configure                                  # paste keys above; region {region}\n"
        f"aws eks update-kubeconfig --name {cluster_name} --region {region}\n"
        "kubectl get nodes                              # expect 3 Ready  (EKS)\n"
        "git clone https://github.com/peopleforrester/KCD_Texas_2026_Workshop.git\n"
        "cd KCD_Texas_2026_Workshop\n"
        "claude"
    )


def _build_email_text(cluster_name, region, access_key, secret_key, root_url):
    # Sections are separated by blank lines and each credential sits on its own
    # line with no leading whitespace or label so triple-click selects just the
    # value in any reasonable mail client.
    bar = "=" * 56
    rule = "-" * 56
    cmds = _build_commands_block(cluster_name, region)
    return (
        f"{bar}\n"
        "Watch It Burn -- Your Cluster Credentials\n"
        f"{bar}\n\n"
        f"Cluster: {cluster_name}\n"
        f"Region:  {region}\n\n"
        f"{rule}\n"
        "AWS Access Key\n"
        f"{rule}\n"
        f"{access_key}\n\n"
        f"{rule}\n"
        "AWS Secret Key\n"
        f"{rule}\n"
        f"{secret_key}\n\n"
        f"{rule}\n"
        "Setup commands\n"
        f"{rule}\n"
        f"{cmds}\n\n"
        "When Claude starts, paste the prompt at the top of spec/BUILD-SPEC.md\n"
        "(the \"How Claude executes this spec\" block). Claude creates the\n"
        "workshop namespaces during Phase 2 -- do not pre-create anything.\n\n"
        "If `kubectl get nodes` shows fewer than 3 Ready nodes, raise your hand\n"
        "during the setup window for a spare cluster.\n\n"
        f"Lost this email? Re-enter your email at {root_url} to redisplay your\n"
        "credentials.\n"
    )


def _build_email_html(cluster_name, region, access_key, secret_key, root_url):
    # Inline styles only - most mail clients strip <style> blocks. System font
    # stack so the message renders without web fonts. Each credential and the
    # commands list lives in its own <pre> so triple-click in Gmail / Outlook
    # web / Apple Mail selects exactly that value.
    cmds = _build_commands_block(cluster_name, region)
    mono_block = (
        "margin:6px 0 0; padding:12px 14px; background:#101A42; color:#FFFFFF;"
        " font-family:Consolas,\"SFMono-Regular\",Menlo,monospace; font-size:13px;"
        " border-radius:6px; white-space:pre; overflow-x:auto; line-height:1.55;"
    )
    label_style = "margin-top:18px; font-size:13px; color:#1E2761; font-weight:600; letter-spacing:.02em;"
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#FDF6EE;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#4A4A4A;line-height:1.5;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FDF6EE;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;background:#FFFFFF;border-radius:10px;border:1px solid #e2e4ee;">
        <tr><td style="background:#1E2761;color:#FFFFFF;padding:18px 24px;border-radius:10px 10px 0 0;border-bottom:3px solid #FF6B35;">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.75;">Watch It Burn</div>
          <div style="font-size:20px;font-weight:700;margin-top:2px;">Your Cluster Credentials</div>
        </td></tr>
        <tr><td style="padding:24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#CADCFC;border-radius:8px;">
            <tr><td style="padding:16px 18px;">
              <div style="font-size:11px;color:#1E2761;letter-spacing:.08em;text-transform:uppercase;opacity:.75;font-weight:700;">Your cluster</div>
              <div style="font-size:22px;color:#1E2761;font-weight:700;margin-top:4px;">{cluster_name}</div>
              <div style="font-size:14px;color:#1E2761;margin-top:4px;">Region: <strong>{region}</strong></div>
            </td></tr>
          </table>

          <div style="{label_style}">AWS access key</div>
          <pre style="{mono_block}">{access_key}</pre>

          <div style="{label_style}">AWS secret key</div>
          <pre style="{mono_block}">{secret_key}</pre>

          <div style="{label_style}">Setup commands</div>
          <pre style="{mono_block}">{cmds}</pre>

          <div style="margin-top:22px;padding:12px 14px;border-left:3px solid #FF6B35;background:#FFF5EE;color:#1E2761;font-size:14px;font-style:italic;border-radius:0 6px 6px 0;">
            <strong style="font-style:normal;">When Claude starts,</strong> paste the prompt at the top of <code style="font-style:normal;font-family:Consolas,monospace;">spec/BUILD-SPEC.md</code> (the &ldquo;How Claude executes this spec&rdquo; block). Claude creates the workshop namespaces during Phase 2 &mdash; do not pre-create anything.
          </div>

          <p style="margin:18px 0 0;color:#4A4A4A;font-size:13px;">
            If <code style="font-family:Consolas,monospace;">kubectl get nodes</code> shows fewer than 3 Ready nodes, raise your hand during the setup window for a spare cluster.
          </p>
        </td></tr>
        <tr><td style="padding:14px 24px 22px;border-top:1px solid #e2e4ee;color:#888888;font-size:12px;text-align:center;font-style:italic;">
          Lost this email? Re-enter your email at <a href="{root_url}" style="color:#FF6B35;text-decoration:none;">the homepage</a> to redisplay your credentials.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_browser_email_text(root_url, kodekloud_url):
    bar = "=" * 56
    rule = "-" * 56
    return (
        f"{bar}\n"
        "Watch It Burn -- Browser Path (KodeKloud)\n"
        f"{bar}\n\n"
        "You're registered for the browser path. KodeKloud provides your\n"
        "cluster directly -- no AWS credentials are needed.\n\n"
        f"{rule}\n"
        "Open KodeKloud\n"
        f"{rule}\n"
        f"{kodekloud_url}\n\n"
        f"{rule}\n"
        "Once you're in the KodeKloud browser shell, run\n"
        f"{rule}\n"
        "curl -fsSL https://claude.ai/install.sh | bash    # install Claude in this shell first\n"
        "kubectl get nodes        # expect 2 Ready  (KodeKloud)\n"
        "git clone https://github.com/peopleforrester/KCD_Texas_2026_Workshop.git\n"
        "cd KCD_Texas_2026_Workshop\n"
        "claude\n\n"
        "When Claude starts, paste the prompt at the top of spec/BUILD-SPEC.md.\n"
        "Claude detects you're on KodeKloud (kubeadm) and adapts Phases 1, 3,\n"
        "and 7 automatically.\n\n"
        f"Lost this email? Re-enter your email at {root_url}/browser to redisplay\n"
        "your registration.\n"
    )


def _build_browser_email_html(root_url, kodekloud_url):
    mono_block = (
        "margin:6px 0 0; padding:12px 14px; background:#101A42; color:#FFFFFF;"
        " font-family:Consolas,\"SFMono-Regular\",Menlo,monospace; font-size:13px;"
        " border-radius:6px; white-space:pre; overflow-x:auto; line-height:1.55;"
    )
    label_style = "margin-top:18px; font-size:13px; color:#1E2761; font-weight:600; letter-spacing:.02em;"
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#FDF6EE;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#4A4A4A;line-height:1.5;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FDF6EE;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;background:#FFFFFF;border-radius:10px;border:1px solid #e2e4ee;">
        <tr><td style="background:#1E2761;color:#FFFFFF;padding:18px 24px;border-radius:10px 10px 0 0;border-bottom:3px solid #FF6B35;">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.75;">Watch It Burn</div>
          <div style="font-size:20px;font-weight:700;margin-top:2px;">Browser path (KodeKloud)</div>
        </td></tr>
        <tr><td style="padding:24px;">
          <p style="margin:0 0 18px;font-size:15px;color:#4A4A4A;">
            You&rsquo;re registered for the browser path. KodeKloud provides your cluster directly &mdash; no AWS credentials needed.
          </p>

          <a href="{kodekloud_url}" style="display:inline-block;background:#FF6B35;color:#FFFFFF;text-decoration:none;font-weight:700;font-size:15px;padding:12px 22px;border-radius:6px;">Open KodeKloud course &rarr;</a>

          <div style="{label_style}">Once you&rsquo;re in the KodeKloud browser shell</div>
          <pre style="{mono_block}">curl -fsSL https://claude.ai/install.sh | bash    # install Claude in this shell first
kubectl get nodes        # expect 2 Ready  (KodeKloud)
git clone https://github.com/peopleforrester/KCD_Texas_2026_Workshop.git
cd KCD_Texas_2026_Workshop
claude</pre>

          <div style="margin-top:22px;padding:12px 14px;border-left:3px solid #FF6B35;background:#FFF5EE;color:#1E2761;font-size:14px;font-style:italic;border-radius:0 6px 6px 0;">
            <strong style="font-style:normal;">When Claude starts,</strong> paste the prompt at the top of <code style="font-style:normal;font-family:Consolas,monospace;">spec/BUILD-SPEC.md</code>. Claude detects you&rsquo;re on KodeKloud (kubeadm) and adapts Phases 1, 3, and 7 automatically.
          </div>
        </td></tr>
        <tr><td style="padding:14px 24px 22px;border-top:1px solid #e2e4ee;color:#888888;font-size:12px;text-align:center;font-style:italic;">
          Lost this email? Re-enter your email at <a href="{root_url}/browser" style="color:#FF6B35;text-decoration:none;">the browser-path form</a> to redisplay your registration.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_resend_email(api_key, to_email, subject, text_body, html_body):
    payload = {
        "from": RESEND_FROM,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    try:
        resp = requests.post(
            RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=RESEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        print(f"[email] send to {to_email} failed: {exc}", flush=True)
        return False
    if 200 <= resp.status_code < 300:
        print(f"[email] sent to {to_email} (status {resp.status_code})", flush=True)
        return True
    print(
        f"[email] send to {to_email} returned {resp.status_code}: {resp.text[:200]}",
        flush=True,
    )
    return False


def create_app(database_path=None, pool_csv=None, resend_api_key=None, eks_pool_limit=None):
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = database_path or os.environ.get("DATABASE_PATH", "./pool.db")
    app.config["POOL_CSV"] = pool_csv or os.environ.get("POOL_CSV", "./pool.csv")
    app.config["ADMIN_TOKEN"] = _resolve_admin_token()
    app.config["RESEND_API_KEY"] = (
        resend_api_key if resend_api_key is not None else os.environ.get("RESEND_API_KEY", "")
    )
    # EKS_POOL_LIMIT caps how many rows of pool.csv get seeded into the live
    # clusters table. The CSV file is left untouched - rows beyond the limit
    # stay on disk but never make it into the active pool. Useful when the CSV
    # holds spare/reserve rows that shouldn't be claimable.
    if eks_pool_limit is None:
        raw = os.environ.get("EKS_POOL_LIMIT", "").strip()
        eks_pool_limit = int(raw) if raw.isdigit() and int(raw) > 0 else None
    app.config["EKS_POOL_LIMIT"] = eks_pool_limit
    # WORKSHOP_HOST appears on the pool-exhausted page ("Ask <host>"). Defaults
    # to a generic phrase so the copy works for any workshop without code edits.
    app.config["WORKSHOP_HOST"] = os.environ.get("WORKSHOP_HOST_NAME", "the workshop host")

    def get_db():
        db = getattr(g, "_db", None)
        if db is None:
            db = sqlite3.connect(app.config["DATABASE_PATH"], isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            g._db = db
        return db

    @app.teardown_appcontext
    def close_db(_exc):
        db = getattr(g, "_db", None)
        if db is not None:
            db.close()

    def init_schema(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clusters (
                id          INTEGER PRIMARY KEY,
                name        TEXT UNIQUE NOT NULL,
                access_key  TEXT NOT NULL,
                secret_key  TEXT NOT NULL,
                region      TEXT NOT NULL,
                claimed_by  TEXT,
                claimed_at  TEXT,
                email_sent  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # In case the table existed from an earlier schema without email_sent.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(clusters)").fetchall()}
        if "email_sent" not in cols:
            conn.execute("ALTER TABLE clusters ADD COLUMN email_sent INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS browser_claims (
                id          INTEGER PRIMARY KEY,
                email       TEXT UNIQUE NOT NULL,
                claimed_at  TEXT NOT NULL
            )
            """
        )

    def seed_from_csv(conn, csv_path):
        if not Path(csv_path).exists():
            return 0
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = [
                (r["name"].strip(), r["access_key"].strip(), r["secret_key"].strip(), r["region"].strip())
                for r in reader
                if r.get("name")
            ]
        limit = app.config.get("EKS_POOL_LIMIT")
        rows_to_seed = rows[:limit] if limit else rows
        inserted = 0
        for name, access_key, secret_key, region in rows_to_seed:
            try:
                conn.execute(
                    "INSERT INTO clusters (name, access_key, secret_key, region) VALUES (?, ?, ?, ?)",
                    (name, access_key, secret_key, region),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                continue
        if limit and len(rows) > limit:
            print(
                f"[startup] pool.csv has {len(rows)} rows; EKS_POOL_LIMIT={limit} so "
                f"rows {limit + 1}-{len(rows)} are left in the file but not seeded",
                flush=True,
            )
        return inserted

    def bootstrap():
        with closing(sqlite3.connect(app.config["DATABASE_PATH"], isolation_level=None)) as conn:
            init_schema(conn)
            (count,) = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()
            if count == 0:
                added = seed_from_csv(conn, app.config["POOL_CSV"])
                print(f"[startup] seeded {added} clusters from {app.config['POOL_CSV']}", flush=True)
            else:
                print(f"[startup] clusters table already has {count} rows; skipping seed", flush=True)
        if app.config["RESEND_API_KEY"]:
            print("[startup] RESEND_API_KEY set - credential emails enabled", flush=True)
        else:
            print("[startup] RESEND_API_KEY not set - email delivery skipped", flush=True)

    bootstrap()

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    @app.get("/")
    def index():
        # The root page is the EKS claim form. The old picker was a one-option
        # interstitial that just added a click; merging it into the form here
        # cuts the time-to-credentials by one interaction per attendee.
        return render_template("index.html")

    @app.get("/eks")
    def eks_form():
        # Back-compat for any QR codes / shared links pointing at /eks.
        return redirect(url_for("index"))

    @app.get("/browser")
    def browser_form():
        return render_template("browser.html")

    @app.post("/browser-claim")
    def browser_claim():
        email = (request.form.get("email") or "").strip().lower()
        if not email or not EMAIL_RE.match(email):
            return render_template("browser.html", error="Please enter a valid email address."), 400

        conn = get_db()
        # Check existence FIRST so we know whether this is a brand-new claim
        # (which should trigger an email) or a re-claim by the same email
        # (which is idempotent and never sends a second email).
        prior = conn.execute(
            "SELECT 1 FROM browser_claims WHERE email = ?", (email,)
        ).fetchone()
        is_new_claim = prior is None
        if is_new_claim:
            conn.execute(
                "INSERT OR IGNORE INTO browser_claims (email, claimed_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (email,),
            )
        row = conn.execute(
            "SELECT email, claimed_at FROM browser_claims WHERE email = ?",
            (email,),
        ).fetchone()

        # Email backup - same pattern as the EKS path. Failures log but never
        # block in-browser display, and re-claims never trigger a second send.
        if is_new_claim and app.config["RESEND_API_KEY"]:
            root = request.url_root.rstrip("/")
            text = _build_browser_email_text(root, KODEKLOUD_COURSE_URL)
            html = _build_browser_email_html(root, KODEKLOUD_COURSE_URL)
            _send_resend_email(
                app.config["RESEND_API_KEY"], email, RESEND_SUBJECT_BROWSER, text, html,
            )

        # Cross-path note: did this email also claim an EKS cluster?
        eks_row = conn.execute(
            "SELECT name, claimed_at FROM clusters WHERE claimed_by = ? LIMIT 1",
            (email,),
        ).fetchone()
        return render_template(
            "browser_success.html",
            email=email,
            claimed_at=row["claimed_at"],
            kodekloud_url=KODEKLOUD_COURSE_URL,
            other_path=({"label": "EKS terminal", "cluster": eks_row["name"], "at": eks_row["claimed_at"]} if eks_row else None),
        )

    @app.post("/eks-claim")
    def eks_claim():
        email = (request.form.get("email") or "").strip().lower()
        if not email or not EMAIL_RE.match(email):
            return render_template("index.html", error="Please enter a valid email address."), 400

        conn = get_db()
        cluster = None
        is_new_claim = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id, name, access_key, secret_key, region, email_sent "
                "FROM clusters WHERE claimed_by = ? LIMIT 1",
                (email,),
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                cluster = existing
            else:
                row = conn.execute(
                    "SELECT id, name, access_key, secret_key, region "
                    "FROM clusters WHERE claimed_by IS NULL ORDER BY id LIMIT 1"
                ).fetchone()
                if row is None:
                    # Pool exhausted for a brand-new email. The browser path is
                    # no longer offered from the main page, so render the
                    # exhausted fallback instead of silently routing to a path
                    # we removed.
                    conn.execute("ROLLBACK")
                    return render_template(
                        "exhausted.html",
                        workshop_host=app.config["WORKSHOP_HOST"],
                    ), 200
                conn.execute(
                    "UPDATE clusters SET claimed_by = ?, "
                    "claimed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                    (email, row["id"]),
                )
                conn.execute("COMMIT")
                cluster = row
                is_new_claim = True
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise

        # Email delivery happens outside the write transaction so we don't hold
        # the SQLite write lock during a network call. Failures are logged but
        # never block the in-browser display, and re-claims by the same email
        # never trigger a second send.
        if is_new_claim and app.config["RESEND_API_KEY"]:
            root = request.url_root.rstrip("/")
            text = _build_email_text(
                cluster["name"], cluster["region"],
                cluster["access_key"], cluster["secret_key"], root,
            )
            html = _build_email_html(
                cluster["name"], cluster["region"],
                cluster["access_key"], cluster["secret_key"], root,
            )
            if _send_resend_email(app.config["RESEND_API_KEY"], email, RESEND_SUBJECT_EKS, text, html):
                conn.execute("UPDATE clusters SET email_sent = 1 WHERE id = ?", (cluster["id"],))

        # Cross-path note: did this email also do a browser claim?
        browser_row = conn.execute(
            "SELECT claimed_at FROM browser_claims WHERE email = ? LIMIT 1",
            (email,),
        ).fetchone()
        return render_template(
            "success.html",
            email=email,
            cluster_name=cluster["name"],
            region=cluster["region"],
            access_key=cluster["access_key"],
            secret_key=cluster["secret_key"],
            root_url=request.url_root.rstrip("/"),
            other_path=({"label": "browser (KodeKloud)", "at": browser_row["claimed_at"]} if browser_row else None),
        )

    @app.post("/claim")
    def claim_back_compat():
        # Back-compat: any external caller or test still hitting POST /claim
        # is forwarded into the canonical EKS-claim handler.
        return eks_claim()

    @app.get("/admin/export")
    def admin_export():
        token = request.args.get("token", "")
        if not token or not secrets.compare_digest(token, app.config["ADMIN_TOKEN"]):
            abort(403)
        conn = get_db()
        eks_rows = conn.execute(
            "SELECT name, region, claimed_by, claimed_at FROM clusters "
            "WHERE claimed_by IS NOT NULL ORDER BY claimed_at"
        ).fetchall()
        br_rows = conn.execute(
            "SELECT email, claimed_at FROM browser_claims ORDER BY claimed_at"
        ).fetchall()
        # One CSV with a leading "path" column so the two paths are easy to
        # sort/filter from any spreadsheet.
        lines = ["path,email,cluster_name,region,claimed_at"]
        for r in eks_rows:
            lines.append(f"eks,{r['claimed_by']},{r['name']},{r['region']},{r['claimed_at']}")
        for r in br_rows:
            lines.append(f"browser,{r['email']},,,{r['claimed_at']}")
        body = "\n".join(lines) + "\n"
        return body, 200, {"Content-Type": "text/csv; charset=utf-8"}

    @app.get("/admin")
    def admin():
        token = request.args.get("token", "")
        if not token or not secrets.compare_digest(token, app.config["ADMIN_TOKEN"]):
            abort(403)
        conn = get_db()
        (eks_total,) = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()
        (eks_claimed,) = conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE claimed_by IS NOT NULL"
        ).fetchone()
        eks_recent = conn.execute(
            "SELECT name, region, claimed_by, claimed_at FROM clusters "
            "WHERE claimed_by IS NOT NULL ORDER BY claimed_at DESC LIMIT 10"
        ).fetchall()
        (browser_count,) = conn.execute("SELECT COUNT(*) FROM browser_claims").fetchone()
        browser_recent = conn.execute(
            "SELECT email, claimed_at FROM browser_claims ORDER BY claimed_at DESC LIMIT 10"
        ).fetchall()
        combined = browser_count + eks_claimed
        browser_pct = round(100 * browser_count / combined) if combined else 0
        eks_pct = 100 - browser_pct if combined else 0
        return render_template(
            "admin.html",
            total=eks_total,
            claimed=eks_claimed,
            available=eks_total - eks_claimed,
            recent=eks_recent,
            browser_count=browser_count,
            browser_recent=browser_recent,
            combined=combined,
            browser_pct=browser_pct,
            eks_pct=eks_pct,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
