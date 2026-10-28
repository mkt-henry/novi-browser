import io
import json
import sys
import unittest
from unittest import mock

from novi_browser import mcp_server as mcp


class MCP(unittest.TestCase):
    def request(self, method, params=None, runner=None):
        return mcp.handle({'jsonrpc': '2.0', 'id': 7, 'method': method, 'params': params or {}}, runner)

    def test_initialize_list_and_notifications(self):
        response = self.request('initialize', {'protocolVersion': '2025-06-18'})
        self.assertEqual(response['id'], 7)
        self.assertEqual(response['result']['protocolVersion'], '2025-06-18')
        # MCP clients get the operating guide without copying any file.
        self.assertTrue(response['result']['instructions'].startswith('# No.VI browser operating guide'))
        names = [t['name'] for t in self.request('tools/list')['result']['tools']]
        self.assertEqual(names, ['list_profiles', 'add_site', 'open', 'exec', 'snap', 'close', 'remember', 'memory'])
        self.assertIsNone(mcp.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_tools_call_same_cli_with_fake(self):
        calls = []
        def fake(argv):
            calls.append(argv)
            print('fake browser response')
            return 0
        examples = [
            ('list_profiles', {}, ['list']),
            ('add_site', {'profile': 'no1', 'site': 'Example', 'check': 'https://example.com', 'signed_out': ['/login']},
             ['add', 'No1', '--site', 'Example', '--check', 'https://example.com', '--signed-out', '/login']),
            ('open', {'profile': 'No1', 'headed': True}, ['open', 'No1', '--headed']),
            ('exec', {'profile': 'No1', 'code': 'snap()', 'timeout': 20}, ['exec', 'No1', '--code', 'snap()', '--timeout', '20']),
            ('snap', {'profile': 'No1', 'selector': 'dialog', 'interactive': True},
             ['exec', 'No1', '--code', "snap(selector='dialog', interactive=True)"]),
            ('close', {'profile': 'No1'}, ['close', 'No1']),
            ('remember', {'profile': 'No1', 'site': 'Example', 'text': 'Use menu'},
             ['remember', 'No1', '--site', 'Example', 'Use menu']),
            ('memory', {'search': 'menu'}, ['memory', '--search', 'menu']),
        ]
        for name, arguments, expected in examples:
            with self.subTest(tool=name):
                response = self.request('tools/call', {'name': name, 'arguments': arguments}, fake)
                self.assertEqual(calls[-1], expected)
                self.assertFalse(response['result']['isError'])
                self.assertEqual(response['result']['content'][0]['text'], 'fake browser response')

    def test_error_codes_and_tool_failures(self):
        self.assertEqual(self.request('unknown')['error']['code'], -32601)
        self.assertEqual(mcp.handle([])['error']['code'], -32600)
        for name, args in [('unknown', {}), ('exec', {'profile': 'No1'}),
                           ('exec', {'profile': 'No1', 'code': '1', 'timeout': -1}),
                           ('open', {'profile': 'No1', 'headed': 'yes'}),
                           ('close', {'profile': 'No1', 'unexpected': 1})]:
            self.assertEqual(self.request('tools/call', {'name': name, 'arguments': args})['error']['code'], -32602)
        response = self.request('tools/call', {'name': 'close', 'arguments': {'profile': 'No1'}}, lambda argv: 1)
        self.assertTrue(response['result']['isError'])

    def test_stdio_recovers_after_bad_json_and_emits_no_notification_response(self):
        incoming = io.StringIO('bad json\n' + json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n' +
                               json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n')
        outgoing = io.StringIO()
        mcp.serve(incoming, outgoing)
        responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]['error']['code'], -32700)
        self.assertEqual(responses[1]['id'], 1)

    def test_remote_call_never_reads_mcp_transport(self):
        transport = io.StringIO('next protocol message\n')
        def fake(argv):
            self.assertEqual(sys.stdin.read(), '')
            return 0
        with mock.patch.object(sys, 'stdin', transport):
            mcp.call_tool('list_profiles', {}, fake)
            self.assertIs(sys.stdin, transport)
            self.assertEqual(transport.read(), 'next protocol message\n')
