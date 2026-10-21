"""Publication failure/recovery tests use fake users and no Feishu network calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feishu-publish/scripts'))
import publisher as p

IDENTITY = {'kind': 'user', 'app_id': 'example-app', 'open_id': 'example-user',
            'tenant_key': '', 'api_base': 'https://open.feishu.cn'}


class FakeAPI:
    token = 'example-private-user-token'
    base = 'https://open.feishu.cn'

    def __init__(self):
        self.calls = []
        self.documents = {}
        self.fail = None
        self.word_wait = False

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.fail and self.fail(method, path):
            raise p.PublishError('example interrupted request ' + self.token)
        if path == '/open-apis/docx/v1/documents':
            doc = 'doc' + str(len(self.documents) + 1)
            self.documents[doc] = {'title': body['title'], 'text': ''}
            return {'document': {'document_id': doc}}
        if path == '/open-apis/drive/v1/import_tasks':
            self.documents['worddoc'] = {'title': body['file_name'], 'text': 'Word正文'}
            return {'ticket': 'example-ticket'}
        if '/import_tasks/' in path:
            if self.word_wait:
                raise p.PublishError('temporarily unreadable')
            return {'result': {'job_status': 0, 'token': 'worddoc'}}
        doc = path.split('/')[5]
        record = self.documents[doc]
        if path.endswith('/children'):
            record['text'] += '\n'.join(b['text']['elements'][0]['text_run']['content'] for b in body['children']) + '\n'
            return {'children': body['children']}
        if path.endswith('/raw_content'):
            return {'content': record['title'] + '\n' + record['text']}
        return {'document': {'title': record['title'], 'revision_id': 1}}

    def upload_word(self, path, data):
        self.calls.append(('UPLOAD', str(path), None))
        return 'example-file-token'


class FakeCLI:
    profile = 'document-publisher'

    def __init__(self, api):
        self.api = api
        self.ok = True
        self.imports = 0

    def import_markdown(self, path, doc, token):
        self.imports += 1
        if token != self.api.token:
            raise AssertionError('wrong user')
        self.api.documents[doc]['text'] = '正文\nEND'
        return {'ok': self.ok, 'partial_failure': not self.ok}


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / 'receipts'
        self.api = FakeAPI()
        self.cli = FakeCLI(self.api)
        self.publisher = p.Publisher(self.root, self.cli, self.api, IDENTITY)
        self.file = self.directory / '报告.md'
        self.file.write_text('# 正文\nEND', encoding='utf-8')

    def publish(self, **kwargs):
        return self.publisher.publish(p.prepare(self.file), **kwargs)

    def mutations(self):
        return [call for call in self.api.calls if call[0] != 'GET']

    def receipt(self, result):
        return p.read_json(self.root / (result['key'] + '.json'))

    def test_publish_dedupe_and_private_receipt(self):
        first = self.publish(expected=['正文', 'END'])
        before = self.mutations()
        second = self.publish()
        self.assertTrue(first['ok'])
        self.assertTrue(second['reused'])
        self.assertEqual(first['url'], second['url'])
        self.assertEqual(before, self.mutations())
        self.assertEqual(self.cli.imports, 1)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        path = self.root / (first['key'] + '.json')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.api.token, path.read_text())
        self.assertFalse(first['readback']['full_rich_content_verified'])

    def test_identity_title_folder_and_copy_are_separate(self):
        original = self.publish()
        other = self.publish(title='另一个标题')
        folder = self.publish(folder='ExampleFolder')
        copy = self.publish(copy_key='weekly-copy')
        self.publisher.identity = dict(IDENTITY, open_id='another-example-user')
        user = self.publish()
        self.assertEqual(len({v['key'] for v in (original, other, folder, copy, user)}), 5)

    def test_partial_does_not_repeat_import_even_on_verify(self):
        self.cli.ok = False
        result = self.publish()
        self.assertFalse(result['ok'])
        self.assertIsNotNone(result['url'])
        self.publish()
        self.publisher.verify(result['key'])
        self.assertEqual(self.cli.imports, 1)
        self.assertEqual(len(self.mutations()), 1)

    def test_unknown_creation_result_is_not_replayed(self):
        self.api.fail = lambda method, path: method == 'POST'
        first = self.publish()
        self.assertEqual(first['state'], 'create_pending')
        self.assertNotIn(self.api.token, json.dumps(first))
        self.api.fail = None
        second = self.publish()
        self.assertFalse(second['ok'])
        self.assertEqual(len(self.mutations()), 1)
        self.assertIsNone(second['url'])

    def test_write_timeout_keeps_created_link(self):
        with patch.object(self.cli, 'import_markdown', side_effect=p.PublishError('timeout')):
            result = self.publish()
        self.assertEqual(result['state'], 'content_pending')
        self.assertTrue(result['url'])
        self.assertFalse(self.publish()['ok'])
        self.assertEqual(self.cli.imports, 0)

    def test_failed_readback_recovers_without_mutation_and_keeps_history(self):
        self.api.fail = lambda method, path: path.endswith('/raw_content')
        first = self.publish()
        self.assertFalse(first['ok'])
        before = self.mutations()
        self.api.fail = None
        verified = self.publisher.verify(first['key'])
        self.assertTrue(verified['ok'])
        self.assertIsNone(verified['error'])
        self.assertEqual(self.mutations(), before)
        self.assertTrue(self.receipt(verified)['failures'])

    def test_failed_reverification_revokes_published_result(self):
        first = self.publish()
        self.api.fail = lambda method, path: method == 'GET'
        verified = self.publisher.verify(first['key'])
        self.assertFalse(verified['ok'])
        self.assertEqual(verified['state'], 'readback_failed')

    def test_plain_text_remains_literal_and_full_text_is_checked(self):
        self.file = self.directory / 'literal.txt'
        self.file.write_text('# literal heading\n**not bold**\nEND', encoding='utf-8')
        result = self.publish()
        self.assertTrue(result['ok'])
        self.assertEqual(self.cli.imports, 0)
        self.assertTrue(result['readback']['plain_text_matches'])
        self.api.documents[result['document_id']]['text'] = '# literal heading'
        self.assertFalse(self.publisher.verify(result['key'])['ok'])

    def test_missing_sentinel_and_title_only_fail(self):
        self.assertFalse(self.publish(expected=['NOT-IN-DOCUMENT'])['ok'])
        self.file.write_text('different input', encoding='utf-8')
        with patch.object(self.cli, 'import_markdown', return_value={'ok': True}):
            self.assertFalse(self.publish()['ok'])

    def test_source_changed_during_import_is_not_success(self):
        original = self.cli.import_markdown
        def changed(*args):
            result = original(*args)
            self.file.write_text('changed during import', encoding='utf-8')
            return result
        with patch.object(self.cli, 'import_markdown', side_effect=changed):
            result = self.publish()
        self.assertFalse(result['ok'])
        self.assertIn('变化', result['error'])

    def test_declared_asset_content_participates_in_hash(self):
        asset = self.directory / 'image.png'
        asset.write_bytes(b'first-image')
        first = p.prepare(self.file, [asset])
        asset.write_bytes(b'second-image')
        second = p.prepare(self.file, [asset])
        self.assertNotEqual(first['sha256'], second['sha256'])

    def test_word_ticket_recovery_never_reuploads(self):
        self.file = self.directory / 'report.docx'
        self.file.write_bytes(b'fake docx handled by mock')
        self.api.word_wait = True
        first = self.publish()
        self.assertFalse(first['ok'])
        self.assertEqual(self.receipt(first)['ticket'], 'example-ticket')
        self.assertFalse(self.publish()['ok'])
        self.api.word_wait = False
        verified = self.publisher.verify(first['key'])
        self.assertTrue(verified['ok'])
        self.assertEqual([call[0] for call in self.mutations()], ['UPLOAD', 'POST'])

    def test_verify_wrong_user_performs_no_reads(self):
        result = self.publish()
        self.publisher.identity = dict(IDENTITY, open_id='wrong-user')
        before = list(self.api.calls)
        with self.assertRaises(p.PublishError):
            self.publisher.verify(result['key'])
        self.assertEqual(self.api.calls, before)

    def test_crash_after_write_started_still_prevents_duplicate(self):
        with patch.object(self.cli, 'import_markdown', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.publish()
        result = self.publish()
        self.assertEqual(result['state'], 'content_pending')
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.mutations()), 1)

    def test_active_lock_rejects_concurrent_writer(self):
        script = 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from publisher import lock;\nwith lock(Path(sys.argv[2]), "same"): pass'
        with p.lock(self.root, 'same'):
            process = subprocess.run([sys.executable, '-c', script, str(ROOT / 'skills/feishu-publish/scripts'),
                                      str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('正在执行', process.stderr)


class BoundaryTests(unittest.TestCase):
    def test_folder_links(self):
        self.assertEqual(p.folder_token('https://example.feishu.cn/drive/folder/Example123'), 'Example123')
        for invalid in ['https://feishu.cn.evil.invalid/drive/folder/a', 'https://a.feishu.cn/wiki/a', '../a']:
            with self.assertRaises(p.PublishError):
                p.folder_token(invalid)

    def test_token_only_in_child_environment_and_no_foreign_feishu_config(self):
        cli = object.__new__(p.CLI)
        cli.profile, cli.binary, cli.config = 'publisher', '/example/cli', Path('/example/config')
        report = {'document_id': 'doc', 'partial_failure': False, 'failures': []}
        process = subprocess.CompletedProcess([], 0, json.dumps(report), '')
        with patch.dict(os.environ, {'FEISHU_APP_SECRET': 'wrong-secret', 'FEISHU_DEBUG': 'true'}), \
             patch.object(p.subprocess, 'run', return_value=process) as run:
            self.assertTrue(cli.import_markdown(Path('/example/report.md'), 'doc', 'private-test-token')['ok'])
        args, kwargs = run.call_args
        self.assertNotIn('private-test-token', str(args))
        self.assertEqual(kwargs['env']['FEISHU_USER_ACCESS_TOKEN'], 'private-test-token')
        self.assertNotIn('FEISHU_APP_SECRET', kwargs['env'])
        self.assertEqual(kwargs['env']['FEISHU_DEBUG'], 'false')

    def test_user_token_error_does_not_request_app_token(self):
        cli = object.__new__(p.CLI)
        with patch.object(cli, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'expired')) as run:
            with self.assertRaises(p.PublishError):
                cli.user_token()
        run.assert_called_once_with(['auth', 'token', '--as', 'user'])

    def test_api_has_pinned_bearer_and_redacts_errors(self):
        api = p.API('https://open.feishu.cn', 'private-test-token')
        error = urllib.error.HTTPError('https://open.feishu.cn', 403, 'denied', {},
                                      io.BytesIO(b'{"code":123,"msg":"private-test-token denied"}'))
        with patch.object(api.opener, 'open', side_effect=error) as opened:
            with self.assertRaises(p.PublishError) as caught:
                api.request('GET', '/open-apis/example')
        self.assertNotIn(api.token, str(caught.exception))
        self.assertEqual(opened.call_args.args[0].get_header('Authorization'), 'Bearer ' + api.token)
        self.assertIsNone(p.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))
        with self.assertRaises(p.PublishError):
            p.API('https://example.invalid', 'token')

    def test_invalid_endpoint_is_rejected_before_token_resolution(self):
        cli = object.__new__(p.CLI)
        with patch.object(cli, "value", side_effect=["https://example.invalid", "example-app"]), \
             patch.object(cli, "user_token") as token:
            with self.assertRaises(p.PublishError):
                p.connect(cli)
        token.assert_not_called()

    def test_word_upload_fields_match_import_api_contract(self):
        api = p.API('https://open.feishu.cn', 'private-test-token')
        with patch.object(api, 'request', return_value={'file_token': 'file'}) as request:
            self.assertEqual(api.upload_word(Path('report.docx'), b'content'), 'file')
        args = request.call_args.args
        self.assertEqual(args[1], '/open-apis/drive/v1/medias/upload_all')
        self.assertIn(b'ccm_import_open', args[2])
        self.assertIn(b'"file_extension": "docx"', args[2])
        self.assertNotIn(b'parent_node', args[2])

    def test_empty_invalid_and_unsupported_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.md'
            for data in [b'', b'\xff']:
                path.write_bytes(data)
                with self.assertRaises(p.PublishError):
                    p.prepare(path)
            path = path.with_suffix('.exe')
            path.write_bytes(b'executable')
            with self.assertRaises(p.PublishError):
                p.prepare(path)


if __name__ == '__main__':
    unittest.main()
