from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from backend.app.services.artifacts import ArtifactStore


TEST_ROOT = Path.cwd() / ".tmp-tests" / "artifact-store"


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if TEST_ROOT.exists():
            shutil.rmtree(TEST_ROOT)

    def test_prepare_run_workspace_creates_default_directories(self) -> None:
        store = ArtifactStore(TEST_ROOT)
        run_root = store.prepare_run_workspace("demo-project", "run-001")

        expected = {"plan", "review", "response", "implementation", "verification", "timeline"}
        actual = {path.name for path in run_root.iterdir() if path.is_dir()}

        self.assertEqual(expected, actual)

    def test_write_text_artifact_persists_markdown_content(self) -> None:
        store = ArtifactStore(TEST_ROOT)
        artifact = store.write_text_artifact(
            project_slug="demo-project",
            run_id="run-001",
            kind="plan",
            version=1,
            content="# Plan\n\n- step one",
        )

        path = Path(artifact.path)
        self.assertTrue(path.exists())
        self.assertEqual("text/markdown", artifact.content_type)
        self.assertEqual("# Plan\n\n- step one", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
