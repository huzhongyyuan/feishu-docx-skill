import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("wrapper", str(ROOT / "bin/feishu-docx"))
spec = importlib.util.spec_from_loader(loader.name, loader)
wrapper = importlib.util.module_from_spec(spec)
loader.exec_module(wrapper)


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "profile/config.yaml"
        self.addCleanup(patch.stopall)
        patch.object(wrapper, "config_path", return_value=self.path).start()
        patch.object(wrapper.shutil, "which", return_value="/example/bin/feishu-cli").start()
        self.execute = patch.object(wrapper.os, "execve").start()

    def config(self, data=None, mode=0o600):
        self.path.parent.mkdir(mode=0o700, exist_ok=True)
        self.path.write_text(json.dumps(data if data is not None else {
            "app_id": "example-app", "app_secret": "example-test-secret"
        }), encoding="utf-8")
        self.path.chmod(mode)

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wrapper.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_missing_config_does_not_launch(self):
        self.assertEqual(self.invoke(["doc", "create", "--title", "test"])[0], 2)
        self.execute.assert_not_called()

    def test_malformed_and_empty_credentials_do_not_launch(self):
        for data in [[], {}, {"app_id": "x", "app_secret": "  "},
                     {"app_id": 12, "app_secret": "secret"}]:
            with self.subTest(data=data):
                self.config(data)
                self.assertEqual(self.invoke(["doc", "get", "example-doc"])[0], 2)
        self.path.write_text("invalid: YAML-without-JSON", encoding="utf-8")
        self.assertEqual(self.invoke(["doc", "get", "example-doc"])[0], 2)
        self.execute.assert_not_called()

    def test_world_readable_config_rejected(self):
        self.config(mode=0o644)
        code, _, err = self.invoke(["doc", "create"])
        self.assertEqual(code, 2)
        self.assertNotIn("example-test-secret", err)
        self.execute.assert_not_called()

    def test_config_symlink_rejected(self):
        self.config()
        target = self.path.with_name("original")
        self.path.rename(target)
        self.path.symlink_to(target)
        self.assertEqual(self.invoke(["doc", "get", "example-doc"])[0], 2)
        self.execute.assert_not_called()

    def test_no_environment_identity_or_owner_override(self):
        self.config()
        overrides = {"FEISHU_APP_ID": "wrong-app", "FEISHU_APP_SECRET": "wrong-secret",
                     "FEISHU_USER_ACCESS_TOKEN": "wrong-token", "FEISHU_PROFILE": "other",
                     "FEISHU_BASE_URL": "https://example.invalid", "FEISHU_DEBUG": "1",
                     "FEISHU_OWNER_EMAIL": "someone@example.invalid",
                     "FEISHU_TRANSFER_OWNERSHIP": "true", "FEISHU_ALLOW_CUSTOM_BASE_URL": "true",
                     "FEISHU_FUTURE_OVERRIDE": "value", "HTTPS_PROXY": "http://proxy.example:8080"}
        with patch.dict(os.environ, overrides):
            self.assertEqual(self.invoke(["doc", "get", "example-doc"])[0], 0)
        binary, argv, env = self.execute.call_args.args
        self.assertEqual(binary, "/example/bin/feishu-cli")
        self.assertEqual(argv[1:5], ["--profile", "feishu-docx", "--config", str(self.path)])
        self.assertFalse(any(k.startswith("FEISHU_") for k in env))
        self.assertEqual(env["HTTPS_PROXY"], overrides["HTTPS_PROXY"])

    def test_override_flags_rejected_in_both_forms(self):
        self.config()
        for flag in wrapper.BLOCKED_FLAGS:
            for args in [[flag, "other", "doc", "get"], ["doc", "get", flag + "=other"]]:
                with self.subTest(args=args):
                    self.assertEqual(self.invoke(args)[0], 2)
        self.execute.assert_not_called()

    def test_offline_help_and_version(self):
        for args in [[], ["--version"], ["-v"], ["--help"], ["doc", "--help"], ["help", "doc"]]:
            with self.subTest(args=args):
                self.assertEqual(self.invoke(args)[0], 0)
        self.assertEqual(self.execute.call_count, 6)

    def test_version_as_title_is_not_credential_bypass(self):
        self.assertEqual(self.invoke(["doc", "create", "--title", "--version"])[0], 2)
        self.execute.assert_not_called()

    def test_missing_dependency_and_recursive_binary(self):
        with patch.object(wrapper.shutil, "which", return_value=None):
            self.assertEqual(self.invoke(["--version"])[0], 2)
        with patch.object(wrapper.shutil, "which", return_value=str(ROOT / "bin/feishu-docx")):
            self.assertEqual(self.invoke(["--version"])[0], 2)
        self.execute.assert_not_called()

    def test_setup_permissions_and_no_secret_output(self):
        with patch.object(sys, "stdin", io.StringIO("example-private-value\n")):
            code, out, err = self.invoke(["setup", "--app-id", "example-app", "--secret-stdin"])
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertEqual(wrapper.read_config(self.path)["app_secret"], "example-private-value")
        self.assertNotIn("example-private-value", out + err)
        self.execute.assert_not_called()

    def test_setup_does_not_overwrite_without_explicit_replace(self):
        self.config()
        before = self.path.read_bytes()
        self.assertEqual(self.invoke(["setup", "--app-id", "new-app", "--secret-stdin"])[0], 2)
        self.assertEqual(self.path.read_bytes(), before)
        with patch.object(sys, "stdin", io.StringIO("new-example-secret")):
            self.assertEqual(self.invoke(["setup", "--app-id", "new-app", "--secret-stdin", "--replace"])[0], 0)
        self.assertEqual(wrapper.read_config(self.path)["app_id"], "new-app")

    def test_setup_empty_secret_leaves_no_config(self):
        with patch.object(sys, "stdin", io.StringIO("\n")):
            self.assertEqual(self.invoke(["setup", "--app-id", "example-app", "--secret-stdin"])[0], 2)
        self.assertFalse(self.path.exists())

    def test_setup_refuses_shared_directory(self):
        self.path.parent.mkdir(mode=0o755)
        self.path.parent.chmod(0o755)
        with patch.object(sys, "stdin", io.StringIO("example-private-value")):
            self.assertEqual(self.invoke(["setup", "--app-id", "example-app", "--secret-stdin"])[0], 2)
        self.assertFalse(self.path.exists())

    def test_setup_preserves_concurrent_config(self):
        actual_link = os.link
        def concurrent_link(source, target):
            Path(target).write_text("another-writer", encoding="utf-8")
            return actual_link(source, target)
        with patch.object(sys, "stdin", io.StringIO("example-private-value")), patch.object(os, "link", side_effect=concurrent_link):
            self.assertEqual(self.invoke(["setup", "--app-id", "example-app", "--secret-stdin"])[0], 2)
        self.assertEqual(self.path.read_text(), "another-writer")
        self.assertEqual(list(self.path.parent.glob(".config-*")), [])

    def test_unicode_and_shell_characters_pass_as_single_arguments(self):
        self.config()
        title = "实验报告 $(echo should-not-run); `id`"
        self.invoke(["doc", "create", "--title", title])
        self.assertEqual(self.execute.call_args.args[1][-1], title)


class InstallTests(unittest.TestCase):
    def test_install_skill_and_preserve_existing_install(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            prefix, codex, claude = base / "local", base / "codex", base / "claude"
            args = [sys.executable, str(ROOT / "scripts/install.py"), "--prefix", str(prefix),
                    "--agent", "codex", "--agent", "claude", "--codex-skills", str(codex),
                    "--claude-skills", str(claude)]
            first = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            command = prefix / "bin/feishu-docx"
            self.assertTrue(command.is_symlink())
            self.assertTrue((codex / "feishu-docx/SKILL.md").is_file())
            self.assertTrue((claude / "feishu-docx/references/access.md").is_file())
            self.assertEqual(command.read_bytes(), (ROOT / "bin/feishu-docx").read_bytes())
            before = command.read_bytes()
            second = subprocess.run(args, text=True, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(command.read_bytes(), before)
            self.assertFalse((base / ".feishu-cli").exists())

    def test_existing_agent_skill_prevents_partial_install(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            (skills / "feishu-docx").mkdir(parents=True)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"),
                                     "--prefix", str(base / "local"), "--agent", "codex",
                                     "--codex-skills", str(skills)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((base / "local/share/feishu-docx-skill").exists())


if __name__ == "__main__":
    unittest.main()
