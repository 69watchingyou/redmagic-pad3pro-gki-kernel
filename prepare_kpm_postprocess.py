"""Fetch only verified same-repository raw inputs; never execute downloaded code here."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile

COMPONENT_RUN = 40548423613
COMPONENT_HEAD = "8bcedbdb0e4a2ff6470b75605be8694efb383d59"
# SHA256 of exact historical git blob bytes (KP and compiler pins included).
COMPONENT_WORKFLOW_SHA256 = "f3488cae386f2a4379a84ffe4677bc63ca7f52639115ba77e95723ba82fe3d8a"
COMPONENT_NAME = "experimental-kpm-abi2-components"
HASHES = {
    "kpimg": "5c7b85922e2cb744c377baa2f42bae5a4ba47811808de72e4da37974882f9bce",
    "kptools": "f4cbef394f994372a5ea0a64a8efd0d8f4f38c28f92167c90f5b5506796cad82",
}
PINS = {
    "kernel": {"commit": "54dcbfbef792fe56756fa60d5f10395a958ac2f1"},
    "integration": {
        "sukisu_commit": "0b666cad90f3a13cb4085f8c88e5144594e82030",
        "susfs_commit": "c51cd8aad3f7e2f8c48bc3bda88cc68cf7d82895",
        "kpm_implementation": "SukiSU_KernelPatch_patch@d958d2582fe3b7eaaeaf238b3bf9af4507a81174",
    },
}
MAX_ARCHIVE = 512 * 1024 * 1024


def numeric_run(value):
    if not re.fullmatch(r"[1-9][0-9]{0,19}", str(value)):
        raise ValueError("Run ID must be positive ASCII digits")
    return int(value)


def check_lock(lock):
    for section, fields in PINS.items():
        for name, value in fields.items():
            if lock.get(section, {}).get(name) != value:
                raise ValueError("Source-lock commit mismatch")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        if not token:
            raise ValueError("Missing read-only token")
        self.base = "https://api.github.com/repos/" + repository
        self.headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "raw-kpm-provenance"}
        self.opener = urllib.request.build_opener(NoRedirect)

    @staticmethod
    def read(response, limit):
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Download size limit exceeded")
        return data

    def get(self, path):
        with self.opener.open(urllib.request.Request(self.base + path, headers=self.headers), timeout=90) as response:
            return json.loads(self.read(response, 8 * 1024 * 1024))

    def archive(self, artifact_id):
        # GitHub redirects to a signed object URL. Never forward the API token there.
        request = urllib.request.Request(self.base + f"/actions/artifacts/{artifact_id}/zip", headers=self.headers)
        try:
            with self.opener.open(request, timeout=90) as response:
                return self.read(response, MAX_ARCHIVE)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers.get("Location", "")
            error.close()
        parsed = urllib.parse.urlsplit(location)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Unsafe artifact redirect")
        # NoRedirect also rejects subsequent redirects, including HTTPS downgrade.
        with self.opener.open(urllib.request.Request(location, headers={"User-Agent": "raw-kpm-provenance"}), timeout=90) as response:
            return self.read(response, MAX_ARCHIVE)


def verified_run(api, repository, run_id, workflow):
    run = api.get(f"/actions/runs/{run_id}")
    path = ".github/workflows/" + workflow
    if (run.get("id") != run_id or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("repository", {}).get("full_name") != repository
            or run.get("head_repository", {}).get("full_name") != repository
            or run.get("path") != path
            or not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))):
        raise ValueError("Untrusted source run")
    identity = api.get(f"/actions/workflows/{workflow}")
    if identity.get("path") != path or run.get("workflow_id") != identity.get("id") or not identity.get("id"):
        raise ValueError("Workflow identity mismatch")
    if run_id == COMPONENT_RUN:
        # Historical component lock predates integration fields (kpm_implementation=null).
        # Authenticate its immutable workflow blob instead, not a later source-lock.
        if workflow != "kpm-tools.yml" or run["head_sha"] != COMPONENT_HEAD:
            raise ValueError("Historical component head mismatch")
        content = api.get("/contents/.github/workflows/kpm-tools.yml?ref=" + COMPONENT_HEAD)
        if content.get("encoding") != "base64":
            raise ValueError("Missing historical component workflow")
        blob = base64.b64decode(content["content"])
        if hashlib.sha256(blob).hexdigest() != COMPONENT_WORKFLOW_SHA256:
            raise ValueError("Historical component workflow hash mismatch")
    else:
        content = api.get("/contents/source-lock.json?ref=" + run["head_sha"])
        if content.get("encoding") != "base64":
            raise ValueError("Missing source lock at run commit")
        check_lock(json.loads(base64.b64decode(content["content"])))
    return run


def verified_artifact(api, run, name):
    matches = []
    page = 1
    while True:
        listing = api.get(f"/actions/runs/{run['id']}/artifacts?per_page=100&page={page}")
        artifacts = listing["artifacts"]
        matches.extend(a for a in artifacts if a.get("name") == name)
        if len(artifacts) < 100:
            break
        page += 1
        if page > 20:
            raise ValueError("Excessive artifact pagination")
    if len(matches) != 1:
        raise ValueError("Expected exactly one named artifact")
    artifact_id = matches[0].get("id")
    if not isinstance(artifact_id, int) or artifact_id <= 0:
        raise ValueError("Invalid artifact ID")
    # Resolve again by ID and verify the artifact's actual run association.
    artifact = api.get(f"/actions/artifacts/{artifact_id}")
    association = artifact.get("workflow_run", {})
    if (artifact.get("id") != artifact_id or artifact.get("name") != name or artifact.get("expired") is not False
            or association.get("id") != run["id"] or association.get("head_sha") != run["head_sha"]
            or not isinstance(artifact.get("id"), int)):
        raise ValueError("Artifact association mismatch or expired artifact")
    return artifact


def verified_archive(api, artifact):
    digest = artifact.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Missing or malformed artifact SHA256 digest")
    data = api.archive(artifact["id"])
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Artifact archive SHA256 mismatch")
    return data


def selected_files(archive, names):
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        result = {}
        for name in names:
            entries = [info for info in source.infolist() if info.filename == name]
            if len(entries) != 1:
                raise ValueError("Missing or duplicate required archive member")
            info = entries[0]
            mode = info.external_attr >> 16
            if info.is_dir() or stat.S_ISLNK(mode) or info.file_size <= 0 or info.file_size > 256 * 1024 * 1024:
                raise ValueError("Invalid archive member")
            result[name] = source.read(info)
        return result


def prepare(api, repository, run_id, directory):
    run_id = numeric_run(run_id)
    check_lock(json.loads(Path("source-lock.json").read_text(encoding="utf-8")))
    candidate = verified_run(api, repository, run_id, "kernel-candidate.yml")
    component = verified_run(api, repository, COMPONENT_RUN, "kpm-tools.yml")
    raw = verified_artifact(api, candidate, f"redmagic-6.6.30-raw-candidate-{run_id}")
    tools = verified_artifact(api, component, COMPONENT_NAME)
    image_path = "work/out/arch/arm64/boot/Image"
    image = selected_files(verified_archive(api, raw), [image_path])[image_path]
    parts = selected_files(verified_archive(api, tools), list(HASHES))
    for name, digest in HASHES.items():
        if hashlib.sha256(parts[name]).hexdigest() != digest:
            raise ValueError("Component SHA256 mismatch")
    # Nothing published/executable until all provenance and hash checks pass.
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, data in {"Image": image, **parts}.items():
        (directory / name).write_bytes(data)
    (directory / "kptools").chmod(0o700)
    provenance = {"repository": repository, "candidate_run_id": run_id, "candidate_head_sha": candidate["head_sha"],
                  "candidate_artifact_id": raw["id"], "component_run_id": COMPONENT_RUN,
                  "component_head_sha": component["head_sha"], "component_artifact_id": tools["id"],
                  "component_workflow_sha256": COMPONENT_WORKFLOW_SHA256,
                  "component_provenance": "Historical source-lock has kpm_implementation=null; exact pinned head and workflow blob authenticate KP d958d2582fe3b7eaaeaf238b3bf9af4507a81174 and compiler SHA256 62d66e0ad7bd7f2a183d236ee301a5c73c737c886c7944aa4f39415aab528daf instead.",
                  "component_sha256": HASHES, "input_sha256": hashlib.sha256(image).hexdigest(),
                  "source_pins": PINS, "experimental": True, "flash_authorized": False}
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=numeric_run)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        prepare(API(repository, os.environ["GH_TOKEN"]), repository, args.run_id, args.directory)
    except Exception as error:
        # HTTP errors may contain signed URLs; never print exceptions, headers or tokens.
        parser.exit(1, "Input preparation rejected (" + type(error).__name__ + "); no postprocessing authorized.\n")
    print("Same-repository run provenance, source pins and fixed component hashes verified.")


if __name__ == "__main__":
    main()
