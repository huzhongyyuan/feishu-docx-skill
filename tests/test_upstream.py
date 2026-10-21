"""Optional, offline contract checks against the real feishu-cli executable.

FEISHU_DOCX_TEST_CLI=/path/to/feishu-cli python3 -m unittest discover -s tests -v
Only config get / --help are invoked, with fake credentials and temporary files.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = os.environ.get("FEISHU_DOCX_TEST_CLI")
RUNNER = """
import runpy, sys
from pathlib import Path
namespace = runpy.run_path(sys.argv[1])
namespace['main'].__globals__['config_path'] = lambda: Path(sys.argv[2])
sys.exit(namespace['main'](sys.argv[3:]))
"""


@unittest.skipUnless(CLI, "set FEISHU_DOCX_TEST_CLI to run real upstream contract checks")
class UpstreamContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / ".feishu-cli/profiles/feishu-docx").mkdir(parents=True)
        self.config = self.directory / "dedicated.json"
        self.config.write_text(json.dumps({"app_id": "example-dedicated-app",
                                          "app_secret": "example-not-a-real-secret",
                                          "base_url": "https://open.feishu.cn",
                                          "transfer_ownership": False}))
        self.config.chmod(0o600)
        # The original CLI searches cwd if an explicit config is not supplied.
        (self.directory / "config.yaml").write_text(json.dumps({
            "app_id": "example-wrong-cwd-app", "app_secret": "example-other-secret"
        }))

    def run_cli(self, *args, extra_env=None):
        # Isolate the child process home; never inspect the real account profiles.
        env = dict(os.environ, FEISHU_DOCX_CLI=CLI, HOME=str(self.directory))
        env.update(extra_env or {})
        return subprocess.run([sys.executable, "-c", RUNNER, str(ROOT / "bin/feishu-docx"),
                               str(self.config), *args], cwd=self.directory, env=env,
                              text=True, capture_output=True, timeout=20)

    def test_real_cli_uses_explicit_config_not_cwd(self):
        result = self.run_cli("config", "get", "app_id")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "example-dedicated-app")

    def test_real_cli_does_not_inherit_other_app(self):
        result = self.run_cli("config", "get", "app_id", extra_env={
            "FEISHU_APP_ID": "example-wrong-env-app", "FEISHU_PROFILE": "other-profile"
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "example-dedicated-app")

    def test_real_cli_does_not_inherit_ownership_or_endpoint(self):
        for key, variable, injected, expected in [
            ("transfer_ownership", "FEISHU_TRANSFER_OWNERSHIP", "true", "false"),
            ("base_url", "FEISHU_BASE_URL", "https://example.invalid", "https://open.feishu.cn"),
            ("owner_email", "FEISHU_OWNER_EMAIL", "someone@example.invalid", ""),
        ]:
            with self.subTest(key=key):
                result = self.run_cli("config", "get", key, extra_env={variable: injected})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_real_cli_document_commands_exist(self):
        for command, required_flag in [("import", "--title"), ("content-update", "--markdown-file"),
                                       ("media-insert", "--file-view"), ("blocks", "--raw")]:
            with self.subTest(command=command):
                result = self.run_cli("doc", command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(required_flag, result.stdout)

    def test_upstream_failure_exit_code_is_preserved(self):
        result = self.run_cli("config", "get", "example-unknown-key")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
