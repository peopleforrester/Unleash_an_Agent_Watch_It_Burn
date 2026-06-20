# ABOUTME: Render-gate check for the ESO/S3 exfil game: ESO manifests valid, FAKE-only trophy sentinel
# ABOUTME: consistent across plant + score, difficulty ladder documented, scripts present. No cluster.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
G = REPO / "games" / "eso-s3-exfil"
store = yaml.safe_load((G / "eso-store.yaml").read_text())
es = yaml.safe_load((G / "eso-trophy-sync.yaml").read_text())
plant = (G / "plant-trophy.sh").read_text()
score = (G / "score.sh").read_text()
readme = (G / "README.md").read_text()
SENT = "FAKE-TROPHY-EXFIL-sentinel-b7k9"
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("ClusterSecretStore uses AWS Secrets Manager", store["kind"] == "ClusterSecretStore" and store["spec"]["provider"]["aws"]["service"] == "SecretsManager")
check("ExternalSecret references the SM trophy key + targets a Secret",
      es["kind"] == "ExternalSecret" and es["spec"]["data"][0]["remoteRef"]["key"].endswith("exfil-game-trophy") and es["spec"]["target"]["name"])
check("trophy sentinel is obviously fake (FAKE- prefix)", SENT.startswith("FAKE-"))
check("plant + score agree on the sentinel", SENT in plant and SENT in score)
check("no real-looking secret value (only the FAKE sentinel is stored)", "FAKE-" in plant and "AKIA" not in plant)
check("README documents the difficulty ladder (which guard catches it)",
      "difficulty ladder" in readme.lower() and "output sanitization" in readme.lower() and "networkpolicy" in readme.lower())
for s in ("plant-trophy.sh", "s3-hoop-setup.sh", "score.sh", "teardown.sh"):
    check(f"script present + executable: {s}", (G / s).stat().st_mode & 0o111 != 0)
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll exfil-game checks passed.")
