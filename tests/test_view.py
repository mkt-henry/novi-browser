import contextlib
import io
import time
import unittest
from unittest import mock
from novi_browser import cli as nb
from test_core import BrowserHome


class Page:

    def __init__(self, url, opener=None):
        self.url, self._opener, self.closed = (url, opener, False)

    def is_closed(self):
        return self.closed

    def opener(self):
        return self._opener


def view_worker():
    worker = nb.Worker.__new__(nb.Worker)
    worker.account, worker.current, worker.viewing, worker.closing = ('No1', '-', False, '')
    worker.spaces, worker.owned, worker.viewed, worker.cards, worker.snaps = ({}, {}, {}, {}, {})
    worker.used = 0.0
    return worker


class ViewLinks(BrowserHome):
    """A link opened in another app (the No.VI app) goes to the profile signed in to its site, in a tab of the
    person's own; a site no profile knows answers 78 so the app opens it in the everyday browser."""

    def test_the_profile_signed_in_to_the_links_site_is_chosen(self):
        nb.add_account('No1', site='Vercel', check='https://vercel.com/dashboard', signed_out=['/login'], user='a')
        nb.add_account('No2', site='Vercel', check='https://vercel.com/dashboard', signed_out=['/login'], user='b')
        nb.set_auth_state('No1', 'Vercel', False, 'https://vercel.com/login')
        nb.set_auth_state('No2', 'Vercel', True, 'https://vercel.com/dashboard')
        nb.add_account('No3', site='Form', check='https://docs.google.com/forms/d/abc/edit', signed_out=['accounts.google.com'], user='c')
        nb.add_account('No4', site='Drive', check='https://drive.google.com/drive/my-drive', signed_out=['accounts.google.com'], user='d')
        self.assertEqual(nb.profile_for('https://vercel.com/team/project'), ('No2', 'Vercel'))
        self.assertEqual(nb.profile_for('https://docs.google.com/forms/d/abc/viewform'), ('No3', 'Form'))
        # Another document on the form's host is no closer to the form than to the Google account: the signed-in one.
        nb.set_auth_state('No4', 'Drive', True, 'https://drive.google.com/drive/my-drive')
        self.assertEqual(nb.profile_for('https://docs.google.com/document/d/xyz/edit')[0], 'No4')
        self.assertEqual(nb.profile_for('https://example.com/'), ('', ''))

    def test_view_opens_it_in_a_window_or_says_78(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(nb.main(['view', 'https://example.com/']), nb.EXIT_NO_ACCOUNT)
        nb.add_account('No1', site='Vercel', check='https://vercel.com/dashboard', signed_out=['/login'], user='a')
        lock = {'pid': 1, 'port': 1, 'token': 't'}
        with mock.patch.object(nb, 'ensure', return_value=(lock, {'ok': True})) as ensure, \
             mock.patch.object(nb, 'wait_turn', return_value=lock), \
             mock.patch.object(nb, 'call_fresh', return_value={'ok': True, 'url': 'https://vercel.com/x', 'hwnd': 42}) as call, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(nb.main(['view', 'https://vercel.com/x']), 0)
        self.assertEqual(ensure.call_args.args[:2], ('No1', '-'))
        self.assertTrue(ensure.call_args.kwargs['headed'])
        self.assertEqual(call.call_args.args[3], '/view')
        self.assertEqual(call.call_args.args[4], {'card': '-', 'url': 'https://vercel.com/x', 'reuse': True})
        self.assertIn('HWND=42', out.getvalue())

    def test_a_link_is_never_sent_to_a_remote_browser(self):
        with mock.patch.object(nb, 'REMOTE_HOST', 'pc'), mock.patch.object(nb, 'forward') as forward, \
             mock.patch.object(nb, 'main', return_value=78) as main, mock.patch.object(nb.sys, 'argv', ['novi-browser', 'view', 'https://a.example/']):
            self.assertEqual(nb.entrypoint(), 78)
        forward.assert_not_called()
        main.assert_called_once_with(['view', 'https://a.example/'])

    def test_a_session_does_not_reopen_the_window_being_read(self):
        nb.add_account('No1', site='Vercel', check='https://vercel.com/dashboard', signed_out=['/login'], user='a')
        lock = {'pid': 1, 'port': 1, 'token': 't', 'headed': False, 'viewing': True, 'cards': {'-': time.time()}}
        with mock.patch.object(nb, 'read_lock', return_value=lock), mock.patch.object(nb, 'close_worker') as close:
            self.assertEqual(nb.ensure('No1', 'session-1')[0], lock)
            with self.assertRaises(nb.BrowserError) as caught:
                nb.ensure('No1', 'session-1', headed=True)
        self.assertEqual(caught.exception.code, nb.EXIT_LOCKED)
        close.assert_not_called()

    def test_the_persons_tabs_keep_the_window_and_their_new_tabs_are_theirs(self):
        worker = view_worker()
        link = Page('https://vercel.com/a')
        session_tab = Page('https://vercel.com/session')
        worker.owned['session-1'] = [session_tab]
        worker.cards = {'-': 1.0, 'session-1': 1.0}
        worker.adopt(link)
        popup = Page('https://vercel.com/b', opener=link)
        own = Page('https://vercel.com/own')
        worker.ctx = mock.Mock(pages=[link, session_tab, popup])
        worker.ctx.new_page.return_value = own
        self.assertTrue(worker.from_view(popup))
        self.assertFalse(worker.from_view(own))
        # A new session's first command finds the popup not yet adopted: it opens a tab of its own instead.
        self.assertIs(worker.page_for('session-2'), own)
        with mock.patch.object(nb, 'update_lock') as lock:
            self.assertTrue(worker.watch_views())
            self.assertIn(popup, worker.owned['-'])
            self.assertNotIn(session_tab, worker.owned['-'])
            worker.used = 0.0
            link.url = 'https://vercel.com/c'
            worker.watch_views()
            self.assertGreater(worker.used, 0)
            link.closed = popup.closed = True
            self.assertFalse(worker.watch_views())
            self.assertNotIn('-', worker.cards)
            self.assertEqual(worker.closing, '')
            lock.assert_called_with('No1', viewing=False, cards=worker.cards)
        worker = view_worker()
        link = Page('https://vercel.com/a')
        worker.cards = {'-': 1.0}
        worker.adopt(link)
        worker.viewing = True
        worker.ctx = mock.Mock(pages=[link])
        link.closed = True
        with mock.patch.object(nb, 'update_lock'):
            worker.watch_views()
        self.assertEqual(worker.closing, 'links closed')


if __name__ == '__main__':
    unittest.main()
