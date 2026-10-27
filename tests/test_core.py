import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from novi_browser import cli as nb
from support import TemporaryDirectory

class BrowserHome(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(nb, 'HOME', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, account='shop-a', **extra):
        return nb.add_account(account, site='Shop', check='https://shop.example/my', signed_out=['/login'], **extra)

class Lock(BrowserHome):

    def test_one_worker_per_account(self):
        self.add()
        self.assertTrue(nb.take_lock('shop-a', {'pid': os.getpid(), 'card': 'a'}))
        self.assertFalse(nb.take_lock('shop-a', {'pid': os.getpid(), 'card': 'b'}))
        self.assertEqual(nb.read_lock('shop-a')['card'], 'a')

    def test_a_crashed_workers_lock_is_cleared(self):
        self.add()
        nb.write_json(nb.lock_path('shop-a'), {'pid': 999999, 'card': 'a'})
        with mock.patch.object(nb, 'pid_alive', return_value=False):
            self.assertIsNone(nb.read_lock('shop-a'))
            self.assertTrue(nb.take_lock('shop-a', {'pid': os.getpid(), 'card': 'b'}))
        self.assertEqual(nb.read_lock('shop-a')['card'], 'b')

    def test_clearing_a_dead_lock_never_removes_a_new_one(self):
        self.add()
        path = nb.lock_path('shop-a')
        nb.write_json(path, {'pid': 999999, 'card': 'a'})
        real_read = nb.read_json
        reads = []

        def replaced_meanwhile(where, default=None):
            value = real_read(where, default)
            if where == path and (not reads):
                reads.append(1)
                nb.write_json(path, {'pid': os.getpid(), 'card': 'b'})
            return value
        with mock.patch.object(nb, 'read_json', side_effect=replaced_meanwhile), mock.patch.object(nb, 'pid_alive', side_effect=lambda pid: int(pid) == os.getpid()):
            self.assertIsNone(nb.read_lock('shop-a'))
        self.assertEqual(real_read(path)['card'], 'b')

    def test_a_running_browser_is_shared_with_another_card(self):
        self.add()
        lock = {'pid': os.getpid(), 'card': 'other', 'cards': {'other': time.time()}, 'port': 1, 'token': 't', 'used': time.time(), 'busy': True, 'card_now': 'other'}
        with mock.patch.object(nb, 'read_lock', return_value=lock), mock.patch.object(nb, 'close_worker') as close, mock.patch.object(nb, 'spawn') as spawn:
            self.assertEqual(nb.ensure('shop-a', 'mine'), (lock, {}))
        close.assert_not_called()
        spawn.assert_not_called()

    def test_a_window_is_not_forced_on_a_browser_another_card_is_using(self):
        self.add()
        lock = {'pid': os.getpid(), 'card': 'other', 'cards': {'other': time.time() - 10}, 'port': 1, 'token': 't', 'used': time.time()}
        with mock.patch.object(nb, 'read_lock', return_value=lock), mock.patch.object(nb, 'close_worker') as close:
            with self.assertRaises(nb.BrowserError) as caught:
                nb.ensure('shop-a', 'mine', headed=True)
        self.assertEqual(caught.exception.code, nb.EXIT_LOCKED)
        close.assert_not_called()
        lock = {**lock, 'cards': {'other': time.time() - 3600}, 'busy': True, 'card_now': 'other'}
        self.assertEqual(nb.others_using(lock, 'mine'), ['other'])
        self.assertEqual(nb.others_using({**lock, 'busy': False}, 'mine'), [])

    def test_closing_a_worker_leaves_a_replacement_alone(self):
        self.add()
        nb.write_json(nb.lock_path('shop-a'), {'pid': os.getpid(), 'card': 'new'})
        with mock.patch.object(nb, 'end_processes') as end, mock.patch.object(nb, 'call') as call:
            self.assertFalse(nb.close_worker('shop-a', 'card over', wait=0, pid=12345))
        end.assert_not_called()
        call.assert_not_called()
        self.assertTrue(nb.lock_path('shop-a').exists())

    def test_only_the_holder_releases_the_lock(self):
        self.add()
        nb.write_json(nb.lock_path('shop-a'), {'pid': os.getpid() + 1, 'card': 'a'})
        nb.release_lock('shop-a')
        self.assertTrue(nb.lock_path('shop-a').exists())
        nb.write_json(nb.lock_path('shop-a'), {'pid': os.getpid(), 'card': 'a'})
        nb.release_lock('shop-a')
        self.assertFalse(nb.lock_path('shop-a').exists())

class Posts(BrowserHome):

    def setUp(self):
        super().setUp()
        self.add()
        self.key = nb.fingerprint('shop-a', '가을 신상', '2026-10-26')

    def test_a_post_whose_outcome_is_unknown_is_not_posted_again(self):
        nb.begin_post('shop-a', self.key, '가을 신상 글', verified=True)
        with self.assertRaises(nb.BrowserError) as caught:
            nb.begin_post('shop-a', self.key, '가을 신상 글', verified=True)
        self.assertIn('UNKNOWN_OUTCOME', str(caught.exception))

    def test_a_done_post_is_not_posted_again_and_a_failed_one_may_be(self):
        nb.begin_post('shop-a', self.key, verified=True)
        nb.end_post('shop-a', self.key, 'done', url='https://shop.example/p/1')
        with self.assertRaises(nb.BrowserError):
            nb.begin_post('shop-a', self.key, verified=True)
        other = nb.fingerprint('shop-a', '겨울 신상', '2026-10-26')
        nb.begin_post('shop-a', other, verified=True)
        nb.end_post('shop-a', other, 'failed', why='버튼 없음')
        self.assertEqual(nb.begin_post('shop-a', other, verified=True)['state'], 'intent')

    def test_nothing_is_posted_without_a_verified_login(self):
        with self.assertRaises(nb.BrowserError) as caught:
            nb.begin_post('shop-a', self.key, verified=False)
        self.assertEqual(caught.exception.code, nb.EXIT_AUTH)
        self.assertEqual(nb.ledger('shop-a'), {})

    def test_resolving_an_unknown_key_is_refused(self):
        with self.assertRaises(nb.BrowserError):
            nb.end_post('shop-a', 'nope', 'done')

    def test_the_fingerprint_ignores_spacing_and_case(self):
        self.assertEqual(nb.fingerprint('A', '가을  신상\n'), nb.fingerprint('a', '가을 신상'))
        self.assertNotEqual(nb.fingerprint('a', '가을 신상'), nb.fingerprint('a', '겨울 신상'))

class Memory(unittest.TestCase):

    def test_a_browser_starts_only_with_room_left(self):
        self.assertTrue(nb.room_for_one(0, 16000)[0])
        self.assertTrue(nb.room_for_one(0, None)[0])
        self.assertFalse(nb.room_for_one(0, nb.MIN_FREE_MB + nb.WORKER_MB - 1)[0])
        self.assertFalse(nb.room_for_one(nb.MAX_WORKERS, 16000)[0])

class Exec(unittest.TestCase):

    def test_the_last_bare_expression_is_returned(self):
        ns = {}
        body, tail = nb.last_expression('x = 2\nx * 21')
        exec(body, ns)
        self.assertEqual(eval(tail, ns), 42)
        self.assertIsNone(nb.last_expression('x = 2')[1])
TREE = '- generic [ref=e1]:\n  - heading "Form" [level=1] [ref=e2]\n  - paragraph [ref=e3]: long text\n  - dialog "Audience" [ref=e5]:\n    - button "Add" [ref=e6]\n    - generic [ref=e7] [cursor=pointer]: Pick\n    - paragraph [ref=e8]: help\n  - button "Save" [ref=e9]'

class Snapshot(unittest.TestCase):

    def test_interactive_keeps_what_can_be_acted_on(self):
        lines = nb.interactive_lines(TREE).splitlines()
        self.assertEqual([line.strip() for line in lines], ['- heading "Form" [level=1] [ref=e2]', '- dialog "Audience" [ref=e5]:', '- button "Add" [ref=e6]', '- generic [ref=e7] [cursor=pointer]: Pick', '- button "Save" [ref=e9]'])

    def test_a_ref_gives_the_element_and_what_is_under_it(self):
        part = nb.subtree(TREE, 'e5')
        self.assertTrue(part.startswith('- dialog "Audience" [ref=e5]:\n  - button "Add"'))
        self.assertNotIn('Save', part)
        self.assertEqual(nb.subtree(TREE, 'e99'), '')

    def test_the_diff_is_the_lines_that_changed(self):
        after = TREE.replace('    - paragraph [ref=e8]: help\n', '') + '\n  - status [ref=e11]: saved'
        self.assertEqual(nb.snapshot_diff(TREE, after), '- - paragraph [ref=e8]: help\n+ - status [ref=e11]: saved')
        self.assertEqual(nb.snapshot_diff(TREE, TREE), '(no changes)')
        self.assertEqual(nb.snapshot_diff('', TREE), TREE)

    def test_a_fixed_wait_ends_when_the_page_stops_changing(self):
        now = [0.0]
        reads = iter(['a', 'b', 'b', 'c'])
        took = nb.calm(None, 3, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0], read=lambda: next(reads))
        self.assertLess(took, 1.2)
        now[0] = 0.0
        busy = nb.calm(None, 2, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0], read=lambda: str(now[0]))
        self.assertAlmostEqual(busy, 2, places=3)
        self.assertEqual(nb.calm(None, 0.1, sleep=lambda s: None, clock=lambda: 0.0), 0.0)

    def test_a_nameless_button_is_shown_with_the_text_under_it(self):
        tree = '- heading [level=5] [ref=f4e2069]: 확인\n  - button [ref=f4e2070] [cursor=pointer]:\n    - generic [ref=f4e9]: 취소\n  - button [ref=f4e2071] [cursor=pointer]:\n    - img [ref=f4e10]\n    - generic [ref=f4e11]: 계속\n  - link [ref=f4e12] [cursor=pointer]:\n    - /url: /x'
        self.assertEqual(nb.interactive_lines(tree).splitlines()[1:], ['  - button [ref=f4e2070] [cursor=pointer]: 취소', '  - button [ref=f4e2071] [cursor=pointer]: 계속', '  - link [ref=f4e12] [cursor=pointer]:'])

    def test_a_ref_is_told_from_a_selector(self):
        page = mock.Mock()
        nb.locate(page, 'e12')
        nb.locate(page, 'f1e2')
        nb.locate(page, 'button.save')
        self.assertEqual([c.args[0] for c in page.locator.call_args_list], ['aria-ref=e12', 'aria-ref=f1e2', 'button.save'])

class Sweep(BrowserHome):

    def test_cards_that_are_over_let_go_unless_a_turn_holds_them(self):
        for account in ('shop-a', 'shop-b'):
            self.add(account)
        locks = {'shop-a': {'card': 'over1', 'cards': {'over1': 1, 'live': 2}, 'pid': 11, 'port': 1}, 'shop-b': {'card': 'over2', 'cards': {'over2': 1, '-': 2}, 'pid': 12, 'port': 2}}
        with mock.patch.object(nb, 'running', return_value=locks), mock.patch.object(nb, 'release', return_value=True) as release:
            touched = nb.sweep(lambda cards: [card for card in cards if card.startswith('over')], busy=lambda: {'over2'})
        self.assertEqual(touched, ['shop-a'])
        release.assert_called_once_with('shop-a', 'over1', pid=11)

    def test_releasing_asks_the_worker_and_closes_one_that_does_not_answer_only_for_its_last_card(self):
        self.add()
        lock = {'pid': 11, 'port': 1, 'token': 't', 'cards': {'a': 1}}
        with mock.patch.object(nb, 'read_lock', return_value=lock), mock.patch.object(nb, 'call', return_value={'ok': True}) as call:
            self.assertTrue(nb.release('shop-a', 'a', pid=11))
            self.assertFalse(nb.release('shop-a', 'a', pid=99))
        call.assert_called_once_with(lock, '/release', {'card': 'a'}, timeout=60)
        with mock.patch.object(nb, 'read_lock', return_value=lock), mock.patch.object(nb, 'call', side_effect=OSError), mock.patch.object(nb, 'close_worker', return_value=True) as close:
            self.assertTrue(nb.release('shop-a', 'a'))
            close.assert_called_once_with('shop-a', 'card over', pid=11)
            close.reset_mock()
            self.assertFalse(nb.release('shop-a', 'b'))
            close.assert_not_called()

    def test_a_worker_that_refuses_the_command_is_replaced_and_the_command_sent_once_more(self):
        import urllib.error
        old = {'pid': 11, 'port': 1, 'token': 't'}
        new = {'pid': 22, 'port': 2, 'token': 'u'}
        locks = iter([old, None])
        with mock.patch.object(nb, 'call', side_effect=[urllib.error.URLError(ConnectionRefusedError()), {'ok': True}]) as call, mock.patch.object(nb, 'read_lock', side_effect=lambda account: next(locks)), mock.patch.object(nb, 'ensure', return_value=(new, {})) as ensure, mock.patch.object(nb, 'wait_turn', return_value=None), mock.patch.object(nb.time, 'sleep'):
            self.assertEqual(nb.call_fresh('shop-a', 'c', old, '/exec', {'code': '1'}, 60, site='Shop'), {'ok': True})
        ensure.assert_called_once_with('shop-a', 'c', headed=False, site='Shop')
        self.assertEqual(call.call_args_list[1].args[0], new)

    def test_a_command_that_may_have_run_is_not_sent_again(self):
        with mock.patch.object(nb, 'call', side_effect=TimeoutError()) as call, mock.patch.object(nb, 'ensure') as ensure:
            with self.assertRaises(TimeoutError):
                nb.call_fresh('shop-a', 'c', {'pid': 11}, '/exec', {'code': 'post()'}, 60)
        call.assert_called_once()
        ensure.assert_not_called()

    def test_nothing_running_asks_nothing(self):
        over = mock.Mock()
        self.assertEqual(nb.sweep(over), [])
        over.assert_not_called()

class Sites(BrowserHome):

    def test_a_profile_is_for_one_login_account(self):
        nb.add_account('No1', site='Shop', check='https://shop.example/my', signed_out=['/login'], user='user@example.com')
        nb.add_account('No1', site='Docs', check='https://docs.example/my', signed_out=['/login'], user='USER@example.com')
        with self.assertRaises(nb.BrowserError) as caught:
            nb.add_account('No1', site='Identity', check='https://identity.example/account', signed_out=['/login'], user='another-user')
        self.assertEqual(caught.exception.code, nb.EXIT_USAGE)
        self.assertIn('No2', str(caught.exception))
        self.assertNotIn('Identity', nb.load_account('No1')['sites'])
        nb.add_account('No2', site='Pay', check='https://pay.example/main', signed_out=['/login'], user='old')
        nb.add_account('No2', site='Pay', check='https://pay.example/main', signed_out=['/login'], user='new')
        self.assertEqual(nb.identity(nb.load_account('No2')), 'new')
        nb.add_account('No3', site='Social', check='https://social.example/accounts/edit/', signed_out=['/login'], who='user')
        self.assertEqual(nb.identity(nb.load_account('No3')), 'user')
        with self.assertRaises(nb.BrowserError):
            nb.add_account('No4', site='A', check='https://a.example/my', signed_out=['/login'], user='alice', who='bob')
        nb.add_account('No4', site='A', check='https://a.example/my', signed_out=['/login'], user='alice')
        with self.assertRaises(nb.BrowserError):
            nb.add_account('No4', site='B', check='https://b.example/my', signed_out=['/login'], user='bob', who='bob')

    def test_profile_names_are_no_and_a_number(self):
        self.assertEqual(nb.profile_name('no1'), 'No1')
        self.assertEqual(nb.profile_name('NO12'), 'No12')
        self.assertEqual(nb.profile_name('No007'), 'No7')
        self.assertEqual(nb.folder('No4').name, 'No4')
        self.assertEqual(nb.next_profile(), 'No1')
        self.add('No1')
        self.add('No4')
        self.assertEqual(nb.next_profile(), 'No5')
        with self.assertRaises(nb.BrowserError):
            nb.folder('Nope')
        with self.assertRaises(nb.BrowserError):
            nb.folder('no1')
        self.assertEqual(nb.profile_name('no1000'), 'No1000')
        self.assertEqual(nb.folder('No1000').name, 'No1000')

    def test_a_login_way_needs_the_page_and_the_password_field(self):
        with self.assertRaises(nb.BrowserError):
            self.add(login={'url': 'https://shop.example/login'})

    def test_each_site_keeps_its_own_login_state(self):
        self.add()
        nb.set_auth_state('shop-a', 'Shop', True, 'https://shop.example/my')
        nb.set_auth_state('shop-a', 'Other', False, 'https://other.example/login')
        state = nb.auth_state('shop-a')
        self.assertEqual((state['Shop']['auth'], state['Other']['auth']), ('READY', 'AUTH_EXPIRED'))

    def test_a_site_added_while_the_browser_runs_is_known_at_the_next_command(self):
        self.add()
        worker = nb.Worker('shop-a', 'card-1', headed=False)
        nb.add_account('shop-a', site='Other', check='https://other.example/my', signed_out=['/login'])
        worker.touch('card-1')
        self.assertEqual(nb.site_config(worker.config, 'Other')[0], 'Other')

    def test_a_site_found_signed_out_is_signed_in_once_by_itself(self):
        self.add(user='me', secret='shop-pw', login={'url': 'https://shop.example/login', 'password_field': '#pw'})
        worker = nb.Worker('shop-a', 'card-1', headed=False)
        with mock.patch.object(nb.Worker, 'check', return_value=False), mock.patch.object(nb.Worker, 'login', return_value=True) as login:
            self.assertTrue(worker.signed_in_or_login('Shop'))
            login.assert_called_once_with('Shop')
            self.assertFalse(worker.signed_in_or_login('Shop'))
            login.assert_called_once()
        self.assertTrue(nb.auth_state('shop-a')['Shop']['auto_login']['ok'])
        finished = []

        def slow(site):
            time.sleep(0.2)
            finished.append(time.time())
            return True
        nb.set_auto_login('shop-a', 'Shop', {'at': 0, 'when': 'long ago', 'ok': True})
        with mock.patch.object(nb.Worker, 'check', return_value=False), mock.patch.object(nb.Worker, 'login', side_effect=slow):
            self.assertTrue(worker.signed_in_or_login('Shop'))
        self.assertGreaterEqual(nb.auto_login_record('shop-a', 'Shop')['at'], finished[0])

    def test_a_site_without_a_saved_way_to_sign_in_is_only_checked(self):
        self.add()
        worker = nb.Worker('shop-a', 'card-1', headed=False)
        with mock.patch.object(nb.Worker, 'check', return_value=False), mock.patch.object(nb.Worker, 'login') as login:
            self.assertFalse(worker.signed_in_or_login('Shop'))
        login.assert_not_called()
