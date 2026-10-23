"""Register the Artikel runner without printing or persisting its registration token."""
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = "PIRANUSA-AI/Article"


def api(path, method="GET"):
    result = subprocess.run(["gh", "api", "--method", method, path], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main():
    runners = api("repos/%s/actions/runners" % REPO)
    existing = next((r for r in runners["runners"] if r["name"] == "artikel-vps"), None)
    if existing:
        print("Runner artikel-vps already registered: %s" % existing["status"], flush=True)
        return
    release = api("repos/actions/runner/releases/latest")
    asset = next(a for a in release["assets"] if a["name"].startswith("actions-runner-linux-x64-") and a["name"].endswith(".tar.gz"))
    digest = (asset.get("digest") or "").removeprefix("sha256:")
    if len(digest) != 64:
        raise RuntimeError("Runner release is missing its SHA256 digest; installation stopped")
    print("Installing runner %s for %s" % (release["tag_name"], REPO), flush=True)
    subprocess.run(["scp", str(ROOT / "scripts/install-article-runner.sh"), str(ROOT / "scripts/deploy-article.sh"), "VPS:/tmp/"], check=True)
    token = api("repos/%s/actions/runners/registration-token" % REPO, "POST")["token"]
    payload = "\n".join([token, asset["browser_download_url"], digest, ""])
    result = subprocess.run(["ssh", "VPS", "bash /tmp/install-article-runner.sh /tmp/deploy-article.sh"],
                            input=payload.encode("utf-8"))
    if result.returncode:
        raise SystemExit(result.returncode)
    state = api("repos/%s/actions/runners" % REPO)
    for runner in state["runners"]:
        print("Runner: %s %s" % (runner["name"], runner["status"]), flush=True)


if __name__ == "__main__":
    main()
