"""Dependency-free MCP stdio transport (newline-delimited JSON-RPC 2.0)."""
from __future__ import annotations

import contextlib
import io
import json
import math
import sys

from . import __version__, cli


def schema(properties=None, required=()):
    return dict(type='object', properties=properties or {}, required=list(required), additionalProperties=False)


STRING = {'type': 'string'}
PROFILE_SITE = {'profile': STRING, 'site': STRING}
TOOLS = [
    ('list_profiles', 'List local profiles, login states and running browsers.', schema()),
    ('add_site', 'Register a site in a profile with the same login identity.', schema({
        **PROFILE_SITE, 'check': STRING, 'signed_out': {'type': 'array', 'items': STRING},
        'signed_in_text': STRING, 'user': STRING, 'secret': STRING, 'identity': STRING,
        'window': {'type': 'boolean'}}, ('profile', 'site', 'check'))),
    ('open', 'Start a profile on demand and check login; headed opens a local window.', schema({
        **PROFILE_SITE, 'headed': {'type': 'boolean'}, 'note': STRING}, ('profile',))),
    ('exec', 'Execute trusted Playwright Python with persistent session variables and helpers.', schema({
        **PROFILE_SITE, 'code': STRING, 'timeout': {'type': 'number', 'exclusiveMinimum': 0}}, ('profile', 'code'))),
    ('snap', 'Read an ARIA snapshot with refs from the session tab.', schema({
        **PROFILE_SITE, 'selector': STRING, 'interactive': {'type': 'boolean'}}, ('profile',))),
    ('close', 'Save login and close a profile (affects all its sessions).', schema({'profile': STRING}, ('profile',))),
    ('remember', 'Append local site know-how.', schema({**PROFILE_SITE, 'text': STRING}, ('profile', 'site', 'text'))),
    ('memory', 'Read site notes or search all local notes.', schema({**PROFILE_SITE, 'search': STRING})),
]


def tool_argv(name, arguments):
    definitions = {n: s for n, _, s in TOOLS}
    if name not in definitions:
        raise ValueError('Unknown tool: ' + name)
    definition = definitions[name]
    if not isinstance(arguments, dict):
        raise ValueError('arguments must be an object')
    if set(arguments) - set(definition['properties']):
        raise ValueError('Unknown arguments')
    for key in definition['required']:
        if key not in arguments:
            raise ValueError('Missing argument: ' + key)
    for key, value in arguments.items():
        kind = definition['properties'][key]['type']
        valid = (isinstance(value, str) if kind == 'string' else
                 isinstance(value, bool) if kind == 'boolean' else
                 isinstance(value, list) and all(isinstance(v, str) for v in value) if kind == 'array' else
                 isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value <= 3600)
        if not valid:
            raise ValueError('Invalid argument: ' + key)
    args = dict(arguments)
    profile = cli.profile_name(args.pop('profile', ''))
    command = {'list_profiles': 'list', 'add_site': 'add', 'snap': 'exec'}.get(name, name)
    argv = [command] + ([profile] if profile else [])
    if name == 'snap':
        selector = args.pop('selector', None)
        interactive = args.pop('interactive', False)
        args['code'] = f'snap(selector={selector!r}, interactive={interactive!r})'
    for key, value in args.items():
        flag = '--' + key.replace('_', '-')
        if key == 'text':
            argv.append(value)
        elif isinstance(value, bool):
            if value:
                argv.append(flag)
        elif isinstance(value, list):
            for item in value:
                argv.extend([flag, item])
        else:
            argv.extend([flag, str(value)])
    if name == 'memory' and not profile and not args.get('search'):
        raise ValueError('Provide a profile or search query')
    return argv


def call_tool(name, arguments, runner=None):
    argv = tool_argv(name, arguments)
    output = io.StringIO()
    transport_input = sys.stdin
    try:
        # The SSH CLI reads stdin for forwarded code; never let it consume the MCP transport.
        sys.stdin = io.StringIO('')
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                code = (runner or (cli.forward if cli.REMOTE_HOST else cli.main))(argv)
            except (SystemExit, cli.BrowserError) as exc:
                code = getattr(exc, 'code', 1)
                print(str(exc))
    finally:
        sys.stdin = transport_input
    return {'content': [{'type': 'text', 'text': output.getvalue().strip() or 'Done.'}], 'isError': code != 0}


def handle(request, runner=None):
    """Handle one request. Notifications return None and never write to stdout."""
    if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
        return error(None, -32600, 'Invalid Request')
    identifier = request.get('id')
    if 'id' not in request:
        return None
    method = request['method']
    params = request.get('params', {})
    if not isinstance(params, dict):
        return error(identifier, -32602, 'params must be an object')
    try:
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                      'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'novi-browser', 'version': __version__}}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': [{'name': n, 'description': d, 'inputSchema': s} for n, d, s in TOOLS]}
        elif method == 'tools/call':
            result = call_tool(params.get('name', ''), params.get('arguments', {}), runner)
        else:
            return error(identifier, -32601, 'Method not found')
    except (ValueError, TypeError) as exc:
        return error(identifier, -32602, str(exc))
    except Exception as exc:
        return {'jsonrpc': '2.0', 'id': identifier, 'result': {
            'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}}
    return {'jsonrpc': '2.0', 'id': identifier, 'result': result}


def error(identifier, code, message):
    return {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': code, 'message': message}}


def serve(input_stream, output_stream, runner=None):
    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except ValueError:
            response = error(None, -32700, 'Parse error')
        else:
            response = handle(request, runner)
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False) + '\n')
            output_stream.flush()


def main():
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    serve(sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
