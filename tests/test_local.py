import contextlib
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from novi_browser import cli as nb
from support import TemporaryDirectory


class LocalHome(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        patch = mock.patch.object(nb, 'HOME', self.home)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_newer_github_version_is_announced_once_a_day_and_update_installs_it(self):
        day = 86400.0
        with mock.patch.dict(os.environ, {nb.UPDATE_ENV: ''}), mock.patch.object(nb, '__version__', '0.1.1'), mock.patch.object(nb, 'latest_version', return_value='0.1.2') as latest:
            first = nb.update_notice(now=day)
            self.assertIn('0.1.2 is available', first)
            self.assertIn('novi-browser update', first)
            self.assertEqual(nb.update_notice(now=day + 60), '')
            self.assertIn('0.1.2', nb.update_notice(always=True, now=day + 60))
            self.assertEqual(latest.call_count, 1)
            nb.update_notice(now=2 * day)
            self.assertEqual(latest.call_count, 2)
        with mock.patch.dict(os.environ, {nb.UPDATE_ENV: ''}), mock.patch.object(nb, '__version__', '0.1.10'), mock.patch.object(nb, 'latest_version', return_value='0.1.9'):
            (self.home / 'update-check.json').unlink()
            self.assertEqual(nb.update_notice(always=True, now=day), '')
        with mock.patch.dict(os.environ, {nb.UPDATE_ENV: ''}), mock.patch.object(nb, 'latest_version', side_effect=OSError('offline')) as latest:
            (self.home / 'update-check.json').unlink()
            self.assertEqual(nb.update_notice(now=day), '')
            self.assertEqual(nb.update_notice(now=day + 60), '')
            self.assertEqual(latest.call_count, 1)
        with mock.patch.dict(os.environ, {nb.UPDATE_ENV: '1'}), mock.patch.object(nb, 'latest_version') as latest:
            self.assertEqual(nb.update_notice(always=True), '')
            latest.assert_not_called()
        out = io.StringIO()
        with mock.patch.object(nb.subprocess, 'call', return_value=0) as call, mock.patch.object(nb, 'installed_version', return_value='0.1.2'), contextlib.redirect_stdout(out):
            self.assertEqual(nb.main(['update']), 0)
        self.assertIn('-> 0.1.2', out.getvalue())
        self.assertFalse((self.home / 'update-check.json').exists())
        command = call.call_args[0][0]
        self.assertTrue(command[:2] == ['git', '-C'] or command[1:5] == ['-m', 'pip', 'install', '--upgrade'])
        with mock.patch.object(nb.subprocess, 'call', return_value=1), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nb.main(['update']), nb.EXIT_FAILED)

    def add(self, name='No1', site='Example'):
        return nb.add_account(name, site=site, check='https://example.com', signed_out=['/signed-out'])

    def test_registration_validation_and_multiple_sites(self):
        for account in ('../outside', 'No1/../No2', '', 'NO1'):
            with self.assertRaises(nb.BrowserError):
                nb.folder(account)
        with self.assertRaises(nb.BrowserError):
            nb.add_account('No1', site='Example', check='example.com', signed_out=['login'])
        with self.assertRaises(nb.BrowserError):
            nb.add_account('No1', site='Example', check='https://example.com', signed_out=[])
        self.add()
        self.add(site='Another')
        self.assertEqual(nb.accounts(), ['No1'])
        self.assertEqual(list(nb.load_account('No1')['sites']), ['Example', 'Another'])
        self.assertTrue((self.home / 'No1/profile').is_dir())

    def test_login_detection(self):
        config = {'signed_out': ['/login'], 'signed_in_text': 'Welcome User'}
        self.assertTrue(nb.signed_in('https://example.com/account', 'Welcome User', config))
        self.assertFalse(nb.signed_in('https://example.com/login', 'Welcome User', config))
        self.assertFalse(nb.signed_in('https://example.com/account', 'Sign in', config))

    def test_local_notes_append_search_read_and_host_match(self):
        first = nb.memory_post({'action': 'note', 'host': 'https://example.com/account', 'site': 'Example', 'text': 'Use the menu'})
        second = nb.memory_post({'action': 'note', 'host': 'https://other.example', 'site': 'Other', 'text': 'Upload as PDF'})
        self.assertEqual(len((self.home / 'memory.jsonl').read_text().splitlines()), 2)
        self.assertEqual(nb.memory_post({'action': 'read', 'key': first['key']})['body'], 'Use the menu')
        found = nb.memory_post({'action': 'search', 'query': 'UPLOAD'})
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['results'][0]['key'], second['key'])
        found = nb.memory_post({'action': 'site', 'hosts': ['https://example.com/another']})
        self.assertEqual([n['key'] for n in found['notes']], [first['key']])
        self.assertEqual(nb.memory_post({'action': 'search', 'query': '', 'kinds': ['other']})['total'], 0)
        with self.assertRaises(nb.BrowserError):
            nb.memory_post({'action': 'read', 'key': 'missing'})

    def test_each_agent_run_adds_a_work_log_line_that_is_searched_not_shown(self):
        answer = json.dumps({'result': 'Compose window open', 'session_id': 's-1'})
        done = mock.Mock(stdout=answer + '\n', stderr='', returncode=0)
        with (
            mock.patch.object(nb, 'load_account', return_value={'sites': {'Example': {}}}),
            mock.patch.object(nb, 'site_config', return_value=('Example', {})),
            mock.patch.object(nb, 'find_claude', return_value='claude'),
            mock.patch.object(nb.subprocess, 'run', return_value=done),
            mock.patch.dict(os.environ, {nb.AGENT_ENV: ''}), contextlib.redirect_stdout(io.StringIO())
        ):
            self.assertEqual(nb.main(['agent', 'No1', '--site', 'Example', 'Open compose']), 0)
        found = nb.memory_post({'action': 'search', 'query': 'compose window', 'kinds': ['episodic']})
        self.assertEqual(found['results'][0]['body'], 'Open compose -> Compose window open')
        self.assertEqual(nb.memory_post({'action': 'site', 'hosts': [], 'names': ['Example']})['notes'], [])
        line = nb.agent_log_line('x' * 500, {'result': 'y', 'is_error': True}, resumed=True)
        self.assertTrue(line.startswith('(resumed) ' + 'x' * (nb.LOG_TASK_CHARS - 1) + '… -> [stopped/error] y'))

    def test_first_open_in_each_session_prints_notes_once(self):
        config = self.add()
        nb.memory_post({'action': 'note', 'host': 'https://example.com', 'site': 'Example', 'text': 'Read this note'})
        out = io.StringIO()
        nb.show_site_memory('No1', config, 'Example', 'session-a', out)
        nb.show_site_memory('No1', config, 'Example', 'session-a', out)
        nb.show_site_memory('No1', config, 'Example', 'session-b', out)
        self.assertEqual(out.getvalue().count('Read this note'), 2)

    def test_secret_priority_env_keyring_file(self):
        nb.write_json(self.home / 'secrets.json', {'site-password': 'file-value'})
        ring = types.SimpleNamespace(get_password=mock.Mock(return_value='keyring-value'))
        with mock.patch.dict(sys.modules, {'keyring': ring}), mock.patch.dict(os.environ, {'NOVI_BROWSER_SECRET_SITE_PASSWORD': 'env-value'}):
            self.assertEqual(nb.secret_value('site-password'), 'env-value')
            ring.get_password.assert_not_called()
        with mock.patch.dict(sys.modules, {'keyring': ring}), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(nb.secret_value('site-password'), 'keyring-value')
            ring.get_password.assert_called_with('novi-browser', 'site-password')
            ring.get_password.return_value = None
            self.assertEqual(nb.secret_value('site-password'), 'file-value')
            ring.get_password.side_effect = RuntimeError('No backend')
            self.assertEqual(nb.secret_value('site-password'), 'file-value')
            with self.assertRaises(nb.BrowserError):
                nb.secret_value('missing')
        if os.name != 'nt':
            self.assertEqual((self.home / 'secrets.json').stat().st_mode & 0o777, 0o600)

    def test_cli_memory_and_remember_share_local_store(self):
        self.add()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(nb.main(['remember', 'No1', '--site', 'Example', 'A useful note']), 0)
            self.assertEqual(nb.main(['memory', 'No1', '--site', 'Example']), 0)
            self.assertEqual(nb.main(['memory', '--search', 'useful']), 0)
        self.assertEqual(output.getvalue().count('A useful note'), 3)

    def test_session_id_is_stable_and_can_be_overridden(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(nb.session_id(), nb.session_id())
        with mock.patch.dict(os.environ, {nb.CARD_ENV: 'explicit-session'}):
            self.assertEqual(nb.session_id(), 'explicit-session')

    def test_cookie_restore_omits_expired_cookies(self):
        self.add()
        worker = nb.Worker('No1', 'session-a', False)
        worker.ctx = mock.Mock()
        nb.write_json(worker.dir / 'session.json', [
            {'name': 'session', 'value': 'x', 'expires': -1},
            {'name': 'expired', 'value': 'x', 'expires': 1},
            {'name': 'future', 'value': 'x', 'expires': 9999999999}])
        worker.restore_session()
        self.assertEqual([c['name'] for c in worker.ctx.add_cookies.call_args.args[0]], ['session', 'future'])
        worker.ctx.cookies.return_value = [{'name': 'session', 'value': 'x', 'expires': -1}]
        worker.save_session()
        self.assertEqual(nb.read_json(worker.dir / 'session.json'), worker.ctx.cookies.return_value)

    def test_intent_requires_the_target_site_to_be_verified(self):
        self.add()
        self.add(site='Other')
        worker = nb.Worker('No1', 'session-a', False, 'Example')
        worker.ctx = mock.Mock()
        worker.verified.add('Other')
        with self.assertRaises(nb.BrowserError):
            worker.helpers('')['intent']('unique-action')
        worker.verified.add('Example')
        worker.helpers('')['intent']('unique-action')
        self.assertEqual(nb.ledger('No1')['unique-action']['state'], 'intent')

    def test_window_hook_is_optional_and_substitutes_without_shell(self):
        self.add()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(nb.subprocess, 'run') as run:
            self.assertIn('locally', nb.share_window('No1', 'session-a', 'Sign in'))
            run.assert_not_called()
        with mock.patch.dict(os.environ, {'NOVI_BROWSER_SHARE_CMD': 'hook "{account}" "{session}" "{note}" "{hwnd}"'}), \
             mock.patch.object(nb, 'browser_window', return_value=42), \
             mock.patch.object(nb.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as run:
            nb.share_window('No1', 'session-a', 'Sign in; do not execute')
        self.assertEqual(run.call_args.args[0], ['hook', 'No1', 'session-a', 'Sign in; do not execute', '42'])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertFalse(nb.unshare_window('No1', 'another-session'))
        self.assertTrue(nb.unshare_window('No1', 'session-a'))

    def test_agent_uses_sonnet_and_preserves_browser_session(self):
        with mock.patch.object(nb, 'find_claude', return_value='claude'), \
             mock.patch.dict(os.environ, {nb.CARD_ENV: 'session-a', 'CLAUDECODE': '1'}):
            argv, env = nb.agent_command('No1', 'Example', 'Inspect the page', session='task-session')
        self.assertEqual(argv[argv.index('--tools') + 1], 'Bash')
        self.assertEqual(env[nb.CARD_ENV], 'session-a')
        self.assertNotIn('CLAUDECODE', env)
        self.assertIn('intent', argv[argv.index('--append-system-prompt') + 1])
        with mock.patch.dict(os.environ, {nb.AGENT_ENV: '1'}), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nb.main(['agent', 'No1', '--site', 'Example', 'Inspect']), nb.EXIT_USAGE)

    def test_remote_file_payload_and_local_default(self):
        (self.home / 'input.txt').write_text('hello')
        payload = nb.forward_payload(['exec', 'No1', '--put', 'input.txt', '-c', 'snap()'], '', 'session-a', self.home)
        self.assertEqual(payload['argv'], ['exec', 'No1', '-c', 'snap()'])
        self.assertEqual(list(payload['files']), ['input.txt'])
        with mock.patch.object(nb, 'REMOTE_HOST', ''), mock.patch.object(sys, 'argv', ['novi-browser', 'list']), \
             mock.patch.object(nb, 'main', return_value=0) as main, mock.patch.object(nb, 'forward') as forward:
            self.assertEqual(nb.entrypoint(), 0)
            main.assert_called_once_with(['list'])
            forward.assert_not_called()

    def test_mdns_features_and_headed_options(self):
        self.assertIn(nb.MDNS_FEATURE, nb.browser_args()[0])
        headed = nb.launch_options(True, 'https://example.com')
        self.assertFalse(headed['headless'])
        self.assertIn('--app=https://example.com', headed['args'])
        self.assertTrue(headed['no_viewport'])
        headless = nb.launch_options(False, '', 'chrome', '150')
        self.assertTrue(headless['headless'])
        self.assertTrue(headless['chromium_sandbox'])
        self.assertNotIn('Headless', headless['user_agent'])

    def test_headless_pages_composite_in_software_and_keep_their_gpu(self):
        for engine in ('chrome', 'chromium'):
            self.assertIn('--disable-gpu-compositing', nb.launch_options(False, '', engine, '150')['args'])
            self.assertNotIn('--disable-gpu', nb.launch_options(False, '', engine, '150')['args'])
            self.assertNotIn('--disable-gpu-compositing', nb.launch_options(True, 'https://example.com', engine)['args'])

    def test_refused_or_interrupted_automatic_login_is_not_repeated(self):
        self.add()
        nb.add_account('No1', site='Example', check='https://example.com', signed_out=['/login'],
                       user='user', secret='password', login={'url': 'https://example.com/login', 'password_field': '#pw'})
        for outcome in (False, None):
            with self.subTest(outcome=outcome):
                nb.set_auto_login('No1', 'Example', {'at': 0, 'when': 'earlier', 'ok': outcome})
                worker = nb.Worker('No1', 'session-a', False)
                with mock.patch.object(nb.Worker, 'check', return_value=False), mock.patch.object(nb.Worker, 'login') as login:
                    self.assertFalse(worker.signed_in_or_login('Example'))
                    login.assert_not_called()

    def test_windows_spawn_fallback_inherits_environment(self):
        self.add()
        with mock.patch.object(nb, 'WINDOWS', True), mock.patch.object(nb.subprocess, 'run', return_value=mock.Mock(returncode=1)), \
             mock.patch.object(nb.subprocess, 'Popen') as popen, \
             mock.patch.dict(os.environ, {'NOVI_BROWSER_SECRET_TEST': 'private-test-value'}):
            nb.spawn('No1', 'session-a', False, 'test-start', 'Example')
        self.assertEqual(popen.call_args.kwargs['env']['NOVI_BROWSER_HOME'], str(self.home.resolve()))
        self.assertEqual(popen.call_args.kwargs['env']['NOVI_BROWSER_SECRET_TEST'], 'private-test-value')
        self.assertFalse(list((self.home / 'No1').glob('environment-*.json')))

    def test_ssh_forward_receives_remote_files(self):
        packet = ('snapshot output\n' + nb.REMOTE_FILES + json.dumps({'result.png': nb.base64_text(b'image')})).encode()
        completed = mock.Mock(returncode=0, stdout=packet, stderr=b'')
        before = Path.cwd()
        try:
            os.chdir(self.home)
            with mock.patch.object(nb, 'REMOTE_HOST', 'user@host'), mock.patch.object(nb.sys, 'stdin', io.StringIO('')), \
                 mock.patch.object(nb.subprocess, 'run', return_value=completed) as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(nb.forward(['exec', 'No1', '-c', "shot('result.png')"]), 0)
            self.assertEqual((self.home / 'result.png').read_bytes(), b'image')
            self.assertEqual(run.call_args.args[0][-2:], ['user@host', 'novi-browser _remote'])
        finally:
            os.chdir(before)
