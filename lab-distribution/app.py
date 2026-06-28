# ABOUTME: Flask app that distributes pre-provisioned per-attendee credentials for Watch It Burn:
# ABOUTME: the cluster console URL, Datadog org login + keys, and AWS keys. Idempotent claim by email.

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
from werkzeug.middleware.proxy_fix import ProxyFix

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

RESEND_ENDPOINT = "https://api.resend.com/emails"
RESEND_FROM = "Watch It Burn Workshop <workshop@agenticburn.com>"
RESEND_SUBJECT = "Watch It Burn Workshop - Your cluster, console, and Datadog access"
RESEND_TIMEOUT_SECONDS = 5

# The per-attendee credential columns carried in pool.csv (beyond name/region). Order matters only
# for readability; everything is read by name. datadog_* come from the observability provisioner
# (Tara's generate_accounts_csv.sh, see README); console_url is the attendee's a-<id> front door.
CRED_COLUMNS = [
    "console_url",
    "datadog_org", "datadog_email", "datadog_password",
    "datadog_api_key", "datadog_app_key", "datadog_site", "datadog_dashboard_url",
]

# Admin exception: these emails get INSTRUCTOR-cluster access (all instructor clusters + the shared
# instructor Datadog account), not an attendee pool row. Everything below the email list is sourced from
# env so no secret lives in the repo (same pattern as RESEND_API_KEY). On the Railway service set:
#   ADMIN_DATADOG_{ORG,EMAIL,PASSWORD,API_KEY,APP_KEY,SITE,DASHBOARD_URL}  (the one instructor DD account)
#   ADMIN_AWS_ACCESS_KEY / ADMIN_AWS_SECRET_KEY  (an IAM key with EKS access to the instructor clusters)
#   ADMIN_REGION (default us-west-2) and ADMIN_CLUSTERS (default = the fleet.sh INSTRUCTORS roster)
DEFAULT_ADMIN_EMAILS = "michaelrishiforrester@gmail.com,wiggitywhitney@gmail.com"
# The admin's own clusters (one per round + an attendee-type), each on its own Whitney-controlled branch
# (whitney-r1/r2/r3/attendee). Override with ADMIN_CLUSTERS for a different admin set.
DEFAULT_INSTRUCTOR_CLUSTERS = (
    "watch-it-burn-whitney-r1,watch-it-burn-whitney-r2,"
    "watch-it-burn-whitney-r3,watch-it-burn-whitney-att"
)
ADMIN_DATADOG_KEYS = [
    "datadog_org", "datadog_email", "datadog_password",
    "datadog_api_key", "datadog_app_key", "datadog_site", "datadog_dashboard_url",
]


def _resolve_admin_token() -> str:
    token = os.environ.get("ADMIN_TOKEN")
    if token:
        return token
    generated = secrets.token_urlsafe(32)
    print(f"[startup] ADMIN_TOKEN not set; using generated token: {generated}", flush=True)
    return generated


def _commands_block(cluster_name, region):
    # The attendee drives the agent from the browser console (chat tab); the terminal/kubectl path
    # below is only needed for the optional shell. No repo clone, no local Claude Code.
    # Use a named profile (watch-it-burn) so attendees who already have AWS configured do not have their
    # default credentials overwritten; attendees with no AWS setup just get this one profile. The profile
    # is baked into the kubeconfig by update-kubeconfig --profile, so kubectl uses it automatically.
    return (
        f"aws configure --profile watch-it-burn         # paste the AWS keys above; region {region}\n"
        f"aws eks update-kubeconfig --name {cluster_name} --region {region} --profile watch-it-burn\n"
        "kubectl get nodes                              # confirm your cluster is up"
    )


def _build_email_text(cred, root_url):
    bar = "=" * 56
    rule = "-" * 56
    cmds = _commands_block(cred["name"], cred["region"])
    dd = (
        f"{rule}\n"
        "Open your Datadog dashboard\n"
        f"{rule}\n"
        f"{cred['datadog_dashboard_url']}\n\n"
        f"Datadog login (to view your org):\n"
        f"  email:    {cred['datadog_email']}\n"
        f"  password: {cred['datadog_password']}\n\n"
        f"{rule}\n"
        "Datadog API key (for your cluster's Agent)\n"
        f"{rule}\n"
        f"{cred['datadog_api_key']}\n\n"
        f"{rule}\n"
        "Datadog APP key\n"
        f"{rule}\n"
        f"{cred['datadog_app_key']}\n\n"
        f"Datadog site: {cred['datadog_site']}\n\n"
    ) if cred.get("datadog_dashboard_url") else ""
    console = (
        f"{rule}\n"
        "Open your workshop console (start here)\n"
        f"{rule}\n"
        f"{cred['console_url']}\n\n"
    ) if cred.get("console_url") else ""
    return (
        f"{bar}\n"
        "Watch It Burn -- Your workshop access\n"
        f"{bar}\n\n"
        f"Cluster: {cred['name']}\n"
        f"Region:  {cred['region']}\n\n"
        f"{console}"
        f"{dd}"
        f"{rule}\n"
        "AWS Access Key (only needed for the terminal / kubectl path)\n"
        f"{rule}\n"
        f"{cred['access_key']}\n\n"
        f"{rule}\n"
        "AWS Secret Key\n"
        f"{rule}\n"
        f"{cred['secret_key']}\n\n"
        f"{rule}\n"
        "Terminal setup commands\n"
        f"{rule}\n"
        f"{cmds}\n\n"
        "Most of the workshop happens in the console (above) -- drive the agent from the\n"
        "chat tab and use the terminal tab for kubectl. The AWS keys are only for the\n"
        "optional local-kubectl fallback.\n\n"
        f"Lost this email? Re-enter your email at {root_url} to redisplay your access.\n"
    )


def _build_email_html(cred, root_url):
    mono = (
        "margin:6px 0 0; padding:12px 14px; background:#101A42; color:#FFFFFF;"
        " font-family:Consolas,\"SFMono-Regular\",Menlo,monospace; font-size:13px;"
        " border-radius:6px; white-space:pre; overflow-x:auto; line-height:1.55;"
    )
    label = "margin-top:18px; font-size:13px; color:#1E2761; font-weight:600; letter-spacing:.02em;"
    btn = ("display:inline-block;background:#FF6B35;color:#FFFFFF;text-decoration:none;"
           "font-weight:700;font-size:15px;padding:12px 22px;border-radius:6px;margin-top:8px;")
    cmds = _commands_block(cred["name"], cred["region"])
    console_html = (
        f'<div style="{label}">Open your workshop console (start here)</div>'
        f'<a href="{cred["console_url"]}" style="{btn}">Open your console &rarr;</a>'
    ) if cred.get("console_url") else ""
    dd_html = (
        f'<div style="{label}">Open your Datadog dashboard</div>'
        f'<a href="{cred["datadog_dashboard_url"]}" style="{btn}">Open Datadog &rarr;</a>'
        f'<div style="{label}">Datadog login (to view your org)</div>'
        f'<pre style="{mono}">email:    {cred["datadog_email"]}\npassword: {cred["datadog_password"]}</pre>'
        f'<div style="{label}">Datadog API key (for your cluster\'s Agent)</div>'
        f'<pre style="{mono}">{cred["datadog_api_key"]}</pre>'
        f'<div style="{label}">Datadog APP key</div>'
        f'<pre style="{mono}">{cred["datadog_app_key"]}</pre>'
        f'<div style="margin-top:6px;font-size:13px;color:#4A4A4A;">Datadog site: <strong>{cred["datadog_site"]}</strong></div>'
    ) if cred.get("datadog_dashboard_url") else ""
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#FDF6EE;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#4A4A4A;line-height:1.5;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FDF6EE;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;background:#FFFFFF;border-radius:10px;border:1px solid #e2e4ee;">
        <tr><td style="background:#1E2761;color:#FFFFFF;padding:18px 24px;border-radius:10px 10px 0 0;border-bottom:3px solid #FF6B35;">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.75;">Watch It Burn</div>
          <div style="font-size:20px;font-weight:700;margin-top:2px;">Your workshop access</div>
        </td></tr>
        <tr><td style="padding:24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#CADCFC;border-radius:8px;">
            <tr><td style="padding:16px 18px;">
              <div style="font-size:11px;color:#1E2761;letter-spacing:.08em;text-transform:uppercase;opacity:.75;font-weight:700;">Your cluster</div>
              <div style="font-size:22px;color:#1E2761;font-weight:700;margin-top:4px;">{cred['name']}</div>
              <div style="font-size:14px;color:#1E2761;margin-top:4px;">Region: <strong>{cred['region']}</strong></div>
            </td></tr>
          </table>
          {console_html}
          {dd_html}
          <div style="{label}">AWS access key <span style="font-weight:400;color:#888;">(only for the terminal / kubectl path)</span></div>
          <pre style="{mono}">{cred['access_key']}</pre>
          <div style="{label}">AWS secret key</div>
          <pre style="{mono}">{cred['secret_key']}</pre>
          <div style="{label}">Terminal setup commands</div>
          <pre style="{mono}">{cmds}</pre>
          <p style="margin:18px 0 0;color:#4A4A4A;font-size:13px;">
            Most of the workshop happens in the console &mdash; drive the agent from the chat tab and use the terminal tab for <code style="font-family:Consolas,monospace;">kubectl</code>. The AWS keys are only for the optional local-kubectl fallback.
          </p>
        </td></tr>
        <tr><td style="padding:14px 24px 22px;border-top:1px solid #e2e4ee;color:#888888;font-size:12px;text-align:center;font-style:italic;">
          Lost this email? Re-enter your email at <a href="{root_url}" style="color:#FF6B35;text-decoration:none;">the homepage</a> to redisplay your access.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_resend_email(api_key, to_email, subject, text_body, html_body):
    payload = {"from": RESEND_FROM, "to": [to_email], "subject": subject,
               "text": text_body, "html": html_body}
    try:
        resp = requests.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            data=json.dumps(payload), timeout=RESEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        print(f"[email] send to {to_email} failed: {exc}", flush=True)
        return False
    if 200 <= resp.status_code < 300:
        print(f"[email] sent to {to_email} (status {resp.status_code})", flush=True)
        return True
    print(f"[email] send to {to_email} returned {resp.status_code}: {resp.text[:200]}", flush=True)
    return False


def create_app(database_path=None, pool_csv=None, resend_api_key=None, eks_pool_limit=None):
    app = Flask(__name__)
    # Served behind the apex Caddy router (provisioning.agenticburn.com), which sets X-Forwarded-*.
    # Trust one proxy hop so request.url_root reflects provisioning.agenticburn.com (not the upstream
    # Railway host) in the success page + email links.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["DATABASE_PATH"] = database_path or os.environ.get("DATABASE_PATH", "./pool.db")
    app.config["POOL_CSV"] = pool_csv or os.environ.get("POOL_CSV", "./pool.csv")
    app.config["ADMIN_TOKEN"] = _resolve_admin_token()
    app.config["RESEND_API_KEY"] = (
        resend_api_key if resend_api_key is not None else os.environ.get("RESEND_API_KEY", "")
    )
    if eks_pool_limit is None:
        raw = os.environ.get("EKS_POOL_LIMIT", "").strip()
        eks_pool_limit = int(raw) if raw.isdigit() and int(raw) > 0 else None
    app.config["EKS_POOL_LIMIT"] = eks_pool_limit
    app.config["WORKSHOP_HOST"] = os.environ.get("WORKSHOP_HOST_NAME", "the workshop host")

    # Admin allowlist + instructor-bundle config (env-sourced; see DEFAULT_ADMIN_EMAILS above).
    app.config["ADMIN_EMAILS"] = {
        e.strip().lower()
        for e in os.environ.get("ADMIN_EMAILS", DEFAULT_ADMIN_EMAILS).split(",")
        if e.strip()
    }
    app.config["ADMIN_REGION"] = os.environ.get("ADMIN_REGION", "us-west-2")
    app.config["ADMIN_CLUSTERS"] = [
        c.strip()
        for c in os.environ.get("ADMIN_CLUSTERS", DEFAULT_INSTRUCTOR_CLUSTERS).split(",")
        if c.strip()
    ]
    app.config["ADMIN_AWS_ACCESS_KEY"] = os.environ.get("ADMIN_AWS_ACCESS_KEY", "")
    app.config["ADMIN_AWS_SECRET_KEY"] = os.environ.get("ADMIN_AWS_SECRET_KEY", "")
    app.config["ADMIN_DATADOG"] = {
        k: os.environ.get("ADMIN_" + k.upper(), "") for k in ADMIN_DATADOG_KEYS
    }
    # Second, dedicated Datadog account for the attendee-type cluster (so its metrics do not mix into
    # the instructor account). Surfaced alongside the instructor account in the admin bundle.
    app.config["ADMIN_ATTENDEE_DATADOG"] = {
        k: os.environ.get("ADMIN_ATTENDEE_" + k.upper(), "") for k in ADMIN_DATADOG_KEYS
    }

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
        # Additive migrations: bring an older clusters table up to the v2 credential set.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(clusters)").fetchall()}
        for col in ["email_sent", *CRED_COLUMNS]:
            if col not in cols:
                default = "0" if col == "email_sent" else "''"
                kind = "INTEGER NOT NULL" if col == "email_sent" else "TEXT NOT NULL"
                conn.execute(f"ALTER TABLE clusters ADD COLUMN {col} {kind} DEFAULT {default}")

    def seed_from_csv(conn, csv_path):
        if not Path(csv_path).exists():
            return 0
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("name")]
        limit = app.config.get("EKS_POOL_LIMIT")
        rows_to_seed = rows[:limit] if limit else rows
        fields = ["name", "access_key", "secret_key", "region", *CRED_COLUMNS]
        inserted = 0
        for r in rows_to_seed:
            vals = [(r.get(f) or "").strip() for f in fields]
            try:
                conn.execute(
                    f"INSERT INTO clusters ({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
                    vals,
                )
                inserted += 1
            except sqlite3.IntegrityError:
                continue
        if limit and len(rows) > limit:
            print(f"[startup] pool.csv has {len(rows)} rows; EKS_POOL_LIMIT={limit} so "
                  f"rows {limit + 1}-{len(rows)} stay in the file but are not seeded", flush=True)
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
        print(f"[startup] RESEND_API_KEY {'set - emails enabled' if app.config['RESEND_API_KEY'] else 'not set - email delivery skipped'}", flush=True)

    bootstrap()

    SELECT_COLS = "id, name, access_key, secret_key, region, " + ", ".join(CRED_COLUMNS)

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    @app.get("/")
    def index():
        # `?as=student` lets an admin (Michael/Whitney) preview the real STUDENT flow; threaded into the
        # claim form as a hidden field so the POST carries it.
        return render_template("index.html", as_param=(request.args.get("as") or ""))

    @app.get("/eks")
    def eks_form():
        return redirect(url_for("index"))

    @app.post("/eks-claim")
    def eks_claim():
        email = (request.form.get("email") or "").strip().lower()
        if not email or not EMAIL_RE.match(email):
            return render_template("index.html", error="Please enter a valid email address."), 400

        # Admin exception: instructor-cluster access, not an attendee pool row. Does not consume the pool.
        # `?as=student` overrides this so an admin can walk the actual STUDENT onboarding (claims a pool row).
        as_student = (request.form.get("as") or request.args.get("as") or "").strip().lower() == "student"
        if email in app.config["ADMIN_EMAILS"] and not as_student:
            region = app.config["ADMIN_REGION"]
            clusters = app.config["ADMIN_CLUSTERS"]
            cmds = "\n".join(
                f"aws eks update-kubeconfig --name {c} --region {region} --profile watch-it-burn"
                for c in clusters
            )
            return render_template(
                "admin_access.html",
                email=email,
                region=region,
                clusters=clusters,
                kubeconfig_commands=cmds,
                aws_access_key=app.config["ADMIN_AWS_ACCESS_KEY"],
                aws_secret_key=app.config["ADMIN_AWS_SECRET_KEY"],
                root_url=request.url_root.rstrip("/"),
                instructor_datadog=app.config["ADMIN_DATADOG"],
                attendee_datadog=app.config["ADMIN_ATTENDEE_DATADOG"],
            )

        conn = get_db()
        cluster = None
        is_new_claim = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT {SELECT_COLS}, email_sent FROM clusters WHERE claimed_by = ? LIMIT 1",
                (email,),
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                cluster = existing
            else:
                row = conn.execute(
                    f"SELECT {SELECT_COLS} FROM clusters WHERE claimed_by IS NULL ORDER BY id LIMIT 1"
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return render_template("exhausted.html", workshop_host=app.config["WORKSHOP_HOST"]), 200
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

        cred = dict(cluster)
        if is_new_claim and app.config["RESEND_API_KEY"]:
            root = request.url_root.rstrip("/")
            text = _build_email_text(cred, root)
            html = _build_email_html(cred, root)
            if _send_resend_email(app.config["RESEND_API_KEY"], email, RESEND_SUBJECT, text, html):
                conn.execute("UPDATE clusters SET email_sent = 1 WHERE id = ?", (cred["id"],))

        return render_template(
            "success.html",
            email=email,
            cluster_name=cred["name"],
            region=cred["region"],
            access_key=cred["access_key"],
            secret_key=cred["secret_key"],
            console_url=cred.get("console_url") or "",
            datadog_dashboard_url=cred.get("datadog_dashboard_url") or "",
            datadog_email=cred.get("datadog_email") or "",
            datadog_password=cred.get("datadog_password") or "",
            datadog_api_key=cred.get("datadog_api_key") or "",
            datadog_app_key=cred.get("datadog_app_key") or "",
            datadog_site=cred.get("datadog_site") or "",
            # Optional per-cluster service URLs/logins, populated by the fleet access-info harvester
            # (issue #37/#15). The template renders gracefully when these are absent.
            burritbot_url=cred.get("burritbot_url") or "",
            argocd_url=cred.get("argocd_url") or "",
            argocd_password=cred.get("argocd_password") or "",
            grafana_url=cred.get("grafana_url") or "",
            grafana_password=cred.get("grafana_password") or "",
            root_url=request.url_root.rstrip("/"),
        )

    @app.post("/claim")
    def claim_back_compat():
        return eks_claim()

    @app.get("/admin/export")
    def admin_export():
        token = request.args.get("token", "")
        if not token or not secrets.compare_digest(token, app.config["ADMIN_TOKEN"]):
            abort(403)
        conn = get_db()
        rows = conn.execute(
            "SELECT name, region, console_url, datadog_org, claimed_by, claimed_at, email_sent "
            "FROM clusters WHERE claimed_by IS NOT NULL ORDER BY claimed_at"
        ).fetchall()
        lines = ["email,cluster_name,region,console_url,datadog_org,claimed_at,email_sent"]
        for r in rows:
            lines.append(f"{r['claimed_by']},{r['name']},{r['region']},{r['console_url']},"
                         f"{r['datadog_org']},{r['claimed_at']},{r['email_sent']}")
        return "\n".join(lines) + "\n", 200, {"Content-Type": "text/csv; charset=utf-8"}

    @app.get("/admin")
    def admin():
        token = request.args.get("token", "")
        if not token or not secrets.compare_digest(token, app.config["ADMIN_TOKEN"]):
            abort(403)
        conn = get_db()
        (total,) = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()
        (claimed,) = conn.execute("SELECT COUNT(*) FROM clusters WHERE claimed_by IS NOT NULL").fetchone()
        recent = conn.execute(
            "SELECT name, region, claimed_by, claimed_at FROM clusters "
            "WHERE claimed_by IS NOT NULL ORDER BY claimed_at DESC LIMIT 10"
        ).fetchall()
        return render_template(
            "admin.html",
            total=total, claimed=claimed, available=total - claimed, recent=recent,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
