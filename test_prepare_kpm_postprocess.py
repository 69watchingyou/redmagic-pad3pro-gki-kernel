import base64
import copy
import io
import json
import hashlib
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import prepare_kpm_postprocess as target


REPO = "owner/repository"
SHA = "a" * 40


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        for name, data in files:
            output.writestr(name, data)
    return stream.getvalue()


class FakeAPI:
    def __init__(self):
        self.run = {"id": 123, "status": "completed", "conclusion": "success", "repository": {"full_name": REPO},
                    "head_repository": {"full_name": REPO}, "path": ".github/workflows/kernel-candidate.yml",
                    "head_sha": SHA, "workflow_id": 456}
        self.artifact = {"id": 789, "name": "candidate", "expired": False,
                         "workflow_run": {"id": 123, "head_sha": SHA}}
        self.lock = copy.deepcopy(target.PINS)
        self.identity = {"id": 456, "path": ".github/workflows/kernel-candidate.yml"}

    def get(self, path):
        if path.startswith("/actions/runs/123/artifacts?"):
            return {"artifacts": [self.artifact]}
        if path == "/actions/artifacts/789":
            return self.artifact
        if path == "/actions/runs/123":
            return self.run
        if path == "/actions/workflows/kernel-candidate.yml":
            return self.identity
        if path.startswith("/contents/source-lock.json?ref="):
            return {"encoding": "base64", "content": base64.b64encode(json.dumps(self.lock).encode()).decode()}
        raise AssertionError(path)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()

    def test_numeric_run(self):
        self.assertEqual(target.numeric_run("40548423613"), 40548423613)
        for value in ("", "-1", "1; echo bad", " 123", "１２３", "0", "1\n", "1.0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                target.numeric_run(value)

    def test_verified_run_and_artifact(self):
        run = target.verified_run(self.api, REPO, 123, "kernel-candidate.yml")
        self.assertEqual(target.verified_artifact(self.api, run, "candidate")["id"], 789)

    def test_bad_run_rejected(self):
        for key, value in (("conclusion", "failure"), ("status", "in_progress"), ("id", 124),
                           ("path", ".github/workflows/other.yml"), ("workflow_id", 999),
                           ("head_sha", "main"), ("head_repository", {"full_name": "attacker/fork"}),
                           ("repository", {"full_name": "other/repo"})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.api = FakeAPI()
                self.api.run[key] = value
                target.verified_run(self.api, REPO, 123, "kernel-candidate.yml")

    def test_workflow_identity_path_rejected(self):
        self.api.identity["path"] = ".github/workflows/other.yml"
        with self.assertRaises(ValueError):
            target.verified_run(self.api, REPO, 123, "kernel-candidate.yml")

    def test_each_source_pin_rejected(self):
        for section, fields in target.PINS.items():
            for name in fields:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    lock = copy.deepcopy(target.PINS)
                    lock[section][name] = "unpinned"
                    target.check_lock(lock)

    def component_api(self, *, blob=None, head=target.COMPONENT_HEAD):
        api = FakeAPI()
        api.lock["integration"]["kpm_implementation"] = None  # actual historical shape
        api.run.update(id=target.COMPONENT_RUN, path=".github/workflows/kpm-tools.yml", head_sha=head)
        api.identity["path"] = ".github/workflows/kpm-tools.yml"
        # Current component workflow is byte-identical to audited historical git blob.
        if blob is None:
            blob = Path(".github/workflows/kpm-tools.yml").read_bytes()
        def get(path):
            if path == f"/actions/runs/{target.COMPONENT_RUN}":
                return api.run
            if path == "/actions/workflows/kpm-tools.yml":
                return api.identity
            if path == "/contents/.github/workflows/kpm-tools.yml?ref=" + target.COMPONENT_HEAD:
                return {"encoding": "base64", "content": base64.b64encode(blob).decode()}
            raise AssertionError("Historical component must not query later source-lock: " + path)
        api.get = get
        return api

    def test_historical_null_lock_accepted_only_via_exact_workflow(self):
        api = self.component_api()
        # The old lock-based validation rejects the real historic shape.
        with self.assertRaisesRegex(ValueError, "Source-lock commit mismatch"):
            target.check_lock(api.lock)
        run = target.verified_run(api, REPO, target.COMPONENT_RUN, "kpm-tools.yml")
        self.assertEqual(run["head_sha"], target.COMPONENT_HEAD)

    def test_historical_workflow_hash_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "workflow hash mismatch"):
            target.verified_run(self.component_api(blob=b"wrong workflow"), REPO, target.COMPONENT_RUN, "kpm-tools.yml")

    def test_historical_head_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "head mismatch"):
            target.verified_run(self.component_api(head="b" * 40), REPO, target.COMPONENT_RUN, "kpm-tools.yml")

    def test_artifact_run_association_rejected(self):
        for key, value in (("id", 999), ("head_sha", "b" * 40)):
            self.api = FakeAPI()
            self.api.artifact["workflow_run"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                target.verified_artifact(self.api, self.api.run, "candidate")

    def test_expired_and_wrong_name_rejected(self):
        self.api.artifact["expired"] = True
        with self.assertRaises(ValueError):
            target.verified_artifact(self.api, self.api.run, "candidate")
        with self.assertRaises(ValueError):
            target.verified_artifact(FakeAPI(), self.api.run, "missing")

    def test_only_exact_archive_paths(self):
        self.assertEqual(target.selected_files(archive([("kpimg", b"payload"), ("../escape", b"evil")]), ["kpimg"]),
                         {"kpimg": b"payload"})
        with self.assertRaises(ValueError):
            target.selected_files(archive([("elsewhere/kpimg", b"x")]), ["kpimg"])
        with self.assertRaises(ValueError):
            target.selected_files(archive([("kpimg", b"")]), ["kpimg"])

    def test_component_hash_failure_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "inputs"
            api = FakeAPI()
            api.archive = lambda artifact_id: archive([("work/out/arch/arm64/boot/Image", b"image"),
                                                        ("kpimg", b"wrong"), ("kptools", b"wrong")])
            api.artifact["digest"] = "sha256:" + hashlib.sha256(api.archive(789)).hexdigest()
            with patch.object(target, "verified_run", return_value=api.run), \
                 patch.object(target, "verified_artifact", return_value=api.artifact), \
                 patch.object(target.Path, "read_text", return_value=json.dumps(target.PINS)):
                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    target.prepare(api, REPO, "123", destination)
            self.assertFalse(destination.exists())

    def test_duplicate_and_symlink_members_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = archive([("kpimg", b"a"), ("kpimg", b"b")])
        with self.assertRaises(ValueError):
            target.selected_files(duplicate, ["kpimg"])
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as output:
            info = zipfile.ZipInfo("kpimg")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(info, b"elsewhere")
        with self.assertRaises(ValueError):
            target.selected_files(stream.getvalue(), ["kpimg"])

    def test_success_stages_only_verified_files_and_provenance(self):
        parts = {"kpimg": b"payload", "kptools": b"tool"}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in parts.items()}
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "inputs"
            api = FakeAPI()
            api.archive = lambda artifact_id: archive([("work/out/arch/arm64/boot/Image", b"image"), *parts.items(),
                                                        ("../never-extracted", b"bad")])
            api.artifact["digest"] = "sha256:" + hashlib.sha256(api.archive(789)).hexdigest()
            with patch.object(target, "verified_run", return_value=api.run), \
                 patch.object(target, "verified_artifact", return_value=api.artifact), \
                 patch.object(target, "HASHES", hashes), \
                 patch.object(target.Path, "read_text", return_value=json.dumps(target.PINS)):
                target.prepare(api, REPO, "123", destination)
            self.assertEqual({p.name for p in destination.iterdir()}, {"Image", "kpimg", "kptools", "provenance.json"})
            provenance = json.loads((destination / "provenance.json").read_text())
            self.assertFalse(provenance["flash_authorized"])
            self.assertEqual(provenance["component_run_id"], 40548423613)
            self.assertEqual((destination / "Image").read_bytes(), b"image")

    def test_archive_digest_required_before_download(self):
        api = FakeAPI()
        api.archive = lambda _: self.fail("download must not happen")
        for value in (None, "", "sha256:wrong", "sha256:" + "G" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                target.verified_archive(api, {"id": 789, "digest": value})

    def test_archive_digest_mismatch_rejected(self):
        api = FakeAPI()
        api.archive = lambda _: b"tampered"
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            target.verified_archive(api, {"id": 789, "digest": "sha256:" + "0" * 64})

    def test_api_missing_token_rejected(self):
        with self.assertRaises(ValueError):
            target.API(REPO, "")


if __name__ == "__main__":
    unittest.main()
