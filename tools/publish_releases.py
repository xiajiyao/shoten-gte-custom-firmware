#!/usr/bin/env python3
"""Publish hash-checked historical experimental releases with GitHub Actions."""

import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "51": (31832, "d8e587ed33e40c3e806f447e192c08cbb971d6716cbf8504f24bcb17c63cd92d"),
    "52": (31940, "fcda2aa0e30f2644ae20700598967fcff25fd032f77b72fd8dfe4cda82c83cd6"),
    "53": (32188, "f4d1828e27f09b1b133680d02cbb061c33a1c1f295f9ffd0e74a827cdb458308"),
    "54": (32184, "1cad2387744d792c6aa0a071b94e4f6330306c6fb6ad2f5a2426ed8f13a4352a"),
    "55": (32472, "01abe933e35a26572aa3fac63c741d69ae3bda55023a74de35796c9ade94373c"),
}


def request(method, url, token, body=None, content_type="application/vnd.github+json"):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": content_type,
    }
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=60) as r:
            result = r.read()
            return json.loads(result) if result else None
    except urllib.error.HTTPError as error:
        detail = error.read(1000).decode("utf-8", "replace")
        if error.code == 404:
            return None
        raise RuntimeError(f"GitHub {method} failed (HTTP {error.code}): {detail}") from error


def main():
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["GITHUB_SHA"]
    if repo != "xiajiyao/shoten-gte-custom-firmware" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Only the intended repository's main branch may publish releases")
    api = f"https://api.github.com/repos/{repo}"
    for number, (size, expected) in EXPECTED.items():
        tag = f"v0.{number}-exp"
        folder = ROOT / "release" / tag
        artifact = folder / f"GTE_ALL_EXP0{number}.bin"
        payload = artifact.read_bytes()
        assert len(payload) == size and hashlib.sha256(payload).hexdigest() == expected, artifact
        assert (folder / "SHA256SUMS").read_text().strip() == f"{expected}  {artifact.name}"
        notes = (folder / "RELEASE_NOTES.md").read_text()
        ref = request("GET", f"{api}/git/ref/tags/{tag}", token)
        if ref is None:
            request("POST", f"{api}/git/refs", token, {"ref": f"refs/tags/{tag}", "sha": sha})
        elif ref["object"]["sha"] != sha:
            print(f"{tag}: existing tag points to a different commit; leaving it unchanged")
        release = request("GET", f"{api}/releases/tags/{tag}", token)
        if release is None:
            release = request("POST", f"{api}/releases", token, {
                "tag_name": tag,
                "name": f"GTE 0.{number} — experimental" + (" (historical, not recommended)" if number == "51" else ""),
                "body": notes,
                "draft": False,
                "prerelease": True,
                "generate_release_notes": False,
            })
        elif release["body"] != notes:
            release = request("PATCH", f"{api}/releases/{release['id']}", token, {"body": notes})
        assets = request("GET", f"{api}/releases/{release['id']}/assets?per_page=100", token)
        if artifact.name not in {asset["name"] for asset in assets}:
            upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release['id']}/assets?{urllib.parse.urlencode({'name': artifact.name})}"
            uploaded = request("POST", upload_url, token, payload, "application/octet-stream")
            if uploaded["size"] != size:
                raise RuntimeError(f"{tag}: uploaded asset size mismatch")
        print(f"{tag}: {release['html_url']} ({artifact.name}, {size} bytes)", flush=True)


if __name__ == "__main__":
    main()
