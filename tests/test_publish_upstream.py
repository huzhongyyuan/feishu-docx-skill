"""Real v1.43.0 converter against a loopback mock; no live Feishu credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feishu-publish/scripts'))
import publisher as p

BINARY = os.environ.get('FEISHU_DOCX_TEST_CLI')


@unittest.skipUnless(BINARY, 'set FEISHU_DOCX_TEST_CLI for real converter contract checks')
class RealPublisherContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.calls, self.blocks = [], []
        self.reject = False
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                owner.calls.append((self.command, self.path, self.headers.get('Authorization'), body))
                if '/blocks/' in self.path and '/children' in self.path:
                    if owner.reject:
                        self.send(400, {'code': 99991663, 'msg': 'user token expired'})
                    else:
                        children = []
                        for block in body['children']:
                            block = dict(block, block_id='block' + str(len(owner.blocks)))
                            owner.blocks.append(block)
                            children.append(block)
                        self.send(200, {'code': 0, 'data': {'children': children, 'document_revision_id': 2}})
                else:
                    self.send(400, {'code': 999999, 'msg': 'unexpected endpoint'})

            def do_GET(self):
                owner.calls.append((self.command, self.path, self.headers.get('Authorization'), None))
                self.send(200, {'code': 0, 'data': {'items': [], 'has_more': False}})

            def send(self, status, body):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cli = object.__new__(p.CLI)
        self.cli.profile = 'publisher-contract'
        self.cli.binary = BINARY
        self.cli.config = self.directory / ".feishu-cli/profiles/publisher-contract/config.yaml"
        self.cli.config.parent.mkdir(parents=True)
        # Only test children see this temporary home; the real profile is untouched.
        isolated = patch.dict(os.environ, {"HOME": str(self.directory)})
        isolated.start()
        self.addCleanup(isolated.stop)
        self.cli.config.write_text(json.dumps({'app_id': 'example-app', 'app_secret': 'example-secret',
                                             'base_url': 'http://127.0.0.1:' + str(self.server.server_port),
                                             'transfer_ownership': True, 'owner_email': 'unused@example.invalid'}))
        self.cli.config.chmod(0o600)
        self.input = self.directory / 'report.md'
        self.input.write_text('# 中文标题\n\n正文段落。\n\n- 列表一\n- 列表二\n\n```python\nprint(42)\n```\n\nEND-MARKER\n', encoding='utf-8')

    def test_real_import_uses_only_user_token_and_existing_document(self):
        report = self.cli.import_markdown(self.input, 'exampledoc123', 'example-user-token')
        self.assertTrue(report['ok'], report)
        self.assertGreater(len(self.blocks), 4)
        self.assertTrue(all(call[2] == 'Bearer example-user-token' for call in self.calls), self.calls)
        self.assertTrue(all('/docx/v1/documents/exampledoc123/blocks/' in call[1] for call in self.calls), self.calls)
        content = json.dumps(self.blocks, ensure_ascii=False)
        self.assertIn('中文标题', content)
        self.assertIn('END-MARKER', content)
        self.assertTrue({3, 12, 14}.issubset({block['block_type'] for block in self.blocks}))

    def test_missing_user_auth_does_not_request_application_token(self):
        with self.assertRaises(p.PublishError):
            self.cli.user_token()
        self.assertEqual(self.calls, [])

    def test_expired_user_import_fails_without_application_fallback(self):
        self.reject = True
        report = self.cli.import_markdown(self.input, 'exampledoc123', 'example-expired-token')
        self.assertFalse(report['ok'])
        self.assertTrue(self.calls)
        self.assertTrue(all(call[2] == 'Bearer example-expired-token' for call in self.calls), self.calls)
        self.assertFalse(any('/auth/' in call[1] or '/permissions/' in call[1] for call in self.calls))


if __name__ == '__main__':
    unittest.main()
