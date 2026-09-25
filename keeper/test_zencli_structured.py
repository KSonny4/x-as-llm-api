"""Structured-output emulation on the text-only CLI (zencli) route."""
import copy
import json

import pytest

import server
import service_api
import service_wire as wire
import zencli_structured as zs
from availability import Result
from credentials import RuntimeCredentials
from inference import HttpResponse
from selection import Selector
from sweeps import Sweeps
from test_api_v2 import call
from test_availability import setup, seed, free, succeed
from zencli_bridge import ZenCLI, bridge_models

# What pydantic's model_json_schema() emits for Cognee's KnowledgeGraph
# (cognee/shared/data_models.py): $defs + $ref, Optional -> anyOf null.
KG_SCHEMA = {
    '$defs': {
        'Edge': {'properties': {
            'source_node_id': {'title': 'Source Node Id', 'type': 'string'},
            'target_node_id': {'title': 'Target Node Id', 'type': 'string'},
            'relationship_name': {'title': 'Relationship Name', 'type': 'string'},
            'description': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None,
                            'title': 'Description'}},
            'required': ['source_node_id', 'target_node_id', 'relationship_name'],
            'title': 'Edge', 'type': 'object'},
        'Node': {'properties': {
            'id': {'title': 'Id', 'type': 'string'},
            'name': {'title': 'Name', 'type': 'string'},
            'type': {'title': 'Type', 'type': 'string'},
            'description': {'title': 'Description', 'type': 'string'}},
            'required': ['id', 'name', 'type', 'description'], 'title': 'Node', 'type': 'object'}},
    'properties': {
        'nodes': {'items': {'$ref': '#/$defs/Node'}, 'title': 'Nodes', 'type': 'array'},
        'edges': {'items': {'$ref': '#/$defs/Edge'}, 'title': 'Edges', 'type': 'array'}},
    'title': 'KnowledgeGraph', 'type': 'object'}

GRAPH = {'nodes': [{'id': 'n1', 'name': 'Keeper', 'type': 'Service', 'description': 'LLM router'},
                   {'id': 'n2', 'name': 'Cognee', 'type': 'Service', 'description': 'memory'}],
         'edges': [{'source_node_id': 'n2', 'target_node_id': 'n1', 'relationship_name': 'calls'}]}


def cognee_request(schema=KG_SCHEMA, text='Cognee calls Keeper.'):
    """Byte-for-byte the litellm_native json-object fallback shape Cognee 1.6.1
    sends for an unknown model like openai/keeper-coder (native_adapter.py
    _acreate_json_fallback): schema in the system prompt, json_object."""
    system = ('You are a knowledge graph extractor.\n\n'
              'You MUST respond with valid JSON conforming to this schema:\n'
              '```json\n%s\n```\nDo not include any text outside the JSON object.'
              % json.dumps(schema, indent=2))
    return {'model': 'keeper-coder', 'messages': [{'role': 'system', 'content': system},
                                                   {'role': 'user', 'content': text}],
            'response_format': {'type': 'json_object'}}


TOOL = {'type': 'function', 'function': {'name': 'KnowledgeGraph', 'description': 'Extract a graph',
                                         'parameters': KG_SCHEMA}}


# ------------------------------------------------------------------ unit: plan

def test_cognee_json_object_plan_embeds_instruction_and_finds_prompt_schema():
    req = cognee_request()
    text_req, sp = zs.plan(req)
    assert set(text_req) == {'model', 'messages'}, 'bridge DisallowUnknownFields: text only'
    assert [m['role'] for m in text_req['messages']] == ['system', 'user']
    assert text_req['messages'][0] == req['messages'][0], 'system prompt verbatim'
    assert text_req['messages'][1]['content'].startswith('Cognee calls Keeper.\n\n')
    assert 'ONLY a single JSON object' in text_req['messages'][1]['content']
    assert sp['kind'] == 'json' and sp['schema'] == KG_SCHEMA
    assert wire.compatible('zencli', req)


def test_plain_text_request_is_passed_through_unchanged():
    req = {'model': 'keeper-coder', 'messages': [{'role': 'system', 'content': 'Be concise'},
                                                 {'role': 'user', 'content': 'hi'}], 'stream': False}
    text_req, sp = zs.plan(req)
    assert sp is None and text_req == req
    assert wire.prepare({'protocol': 'zencli', 'model': 'big-pickle'}, req) == {**req, 'model': 'big-pickle'}


def test_generation_controls_are_dropped_and_streaming_stays_incompatible():
    base = cognee_request()
    loud = {**base, 'temperature': 0.0, 'max_tokens': 4096, 'seed': 7, 'top_p': 1,
            'parallel_tool_calls': False, 'stop': ['\n\n\n']}
    payload = wire.prepare({'protocol': 'zencli', 'model': 'm'}, loud)
    assert set(payload) == {'model', 'messages'} and payload['model'] == 'm'
    for bad in ({'stream': True}, {'n': 2}, {'logprobs': True}):
        assert not wire.compatible('zencli', {**base, **bad})
    tools = {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'x'}],
             'tools': [TOOL, {**TOOL, 'function': {**TOOL['function'], 'name': 'Other'}}]}
    assert not wire.compatible('zencli', tools), 'auto with several tools is not emulated'
    assert wire.compatible('zencli', {**tools, 'tool_choice': 'required'})
    assert wire.compatible('zencli', {**tools, 'tool_choice': 'none'})


def test_json_schema_and_forced_tool_instructions_carry_the_schema():
    req = {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'extract'}],
           'response_format': {'type': 'json_schema', 'json_schema': {
               'name': 'KnowledgeGraph', 'strict': True, 'schema': KG_SCHEMA}}}
    text_req, sp = zs.plan(req)
    note = text_req['messages'][-1]['content']
    assert '"KnowledgeGraph"' in note and json.dumps(KG_SCHEMA, separators=(',', ':')) in note
    forced = {'model': 'keeper-coder', 'messages': [{'role': 'system', 'content': 'sys'}],
              'tools': [TOOL], 'tool_choice': {'type': 'function', 'function': {'name': 'KnowledgeGraph'}}}
    text_req, sp = zs.plan(forced)
    assert sp['mode'] == 'forced' and text_req['messages'][-1]['role'] == 'user'
    assert 'must call the function "KnowledgeGraph"' in text_req['messages'][-1]['content']


def test_tool_history_is_flattened_into_bridge_legal_text_turns():
    req = {'model': 'keeper-coder', 'tools': [TOOL], 'tool_choice': 'auto', 'messages': [
        {'role': 'developer', 'content': 'dev rules'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'part one '}, {'type': 'text', 'text': 'two'}]},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call_1', 'type': 'function', 'function': {'name': 'KnowledgeGraph', 'arguments': '{"nodes":[]}'}}]},
        {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'stored'},
    ]}
    assert wire.compatible('zencli', req)
    payload = wire.prepare({'protocol': 'zencli', 'model': 'm'}, req)
    msgs = payload['messages']
    assert all(set(m) == {'role', 'content'} and isinstance(m['content'], str) and
               m['role'] in ('system', 'user', 'assistant') for m in msgs)
    assert msgs[0] == {'role': 'system', 'content': 'dev rules'}
    assert msgs[1]['content'] == 'part one two'
    assert 'KnowledgeGraph' in msgs[2]['content'] and 'call_1' in msgs[2]['content'], 'tool-only turn not dropped'
    assert msgs[3]['role'] == 'user' and 'stored' in msgs[3]['content'] and 'KnowledgeGraph' in msgs[3]['content']


def test_prompts_beyond_the_cli_argument_limit_are_not_routed_to_the_cli():
    huge = cognee_request(text='x' * (zs.PROMPT_LIMIT + 1))
    assert not wire.compatible('zencli', huge)
    assert wire.compatible('openai', huge)


# ------------------------------------------------------- unit: parse/validate

@pytest.mark.parametrize('text', [
    json.dumps(GRAPH),
    '```json\n%s\n```' % json.dumps(GRAPH, indent=2),
    'Here is the graph you asked for:\n```\n%s\n```\nLet me know!' % json.dumps(GRAPH),
    'Sure! %s' % json.dumps(GRAPH),
])
def test_extract_json_strips_fences_and_prose(text):
    assert zs.extract_json(text) == GRAPH


def test_extract_json_handles_braces_inside_strings_and_rejects_prose():
    tricky = 'note {not json} then {"a": "} {", "b": [1, {"c": 2}]} trailing'
    assert zs.extract_json(tricky) == {'a': '} {', 'b': [1, {'c': 2}]}
    with pytest.raises(zs.Invalid):
        zs.extract_json('I cannot help with that.')


def test_validator_covers_pydantic_defs_refs_optional_and_prunes_extras():
    strict = copy.deepcopy(KG_SCHEMA)
    strict['$defs']['Node']['additionalProperties'] = False
    extra = copy.deepcopy(GRAPH)
    extra['nodes'][0]['confidence'] = 0.9
    extra['edges'][0]['description'] = None
    assert zs.conform(extra, strict)['nodes'][0] == GRAPH['nodes'][0], 'extra pruned, not rejected'
    missing = copy.deepcopy(GRAPH)
    del missing['nodes'][1]['type']
    with pytest.raises(zs.Invalid, match=r'\$\.nodes\[1\].*"type"'):
        zs.conform(missing, KG_SCHEMA)
    wrong = copy.deepcopy(GRAPH)
    wrong['edges'][0]['description'] = 5
    with pytest.raises(zs.Invalid, match='alternatives'):
        zs.conform(wrong, KG_SCHEMA)
    schema = {'type': 'object', 'properties': {'kind': {'enum': ['a', 'b']}, 'n': {'type': 'integer', 'minimum': 0},
              'tags': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 2}}, 'required': ['kind']}
    assert zs.conform({'kind': 'a', 'n': 3.0, 'tags': ['x']}, schema)['n'] == 3.0
    for bad in ({'kind': 'c'}, {'kind': 'a', 'n': -1}, {'kind': 'a', 'n': True},
                {'kind': 'a', 'tags': ['x', 'y', 'z']}, {'kind': 'a', 'tags': [1]}):
        with pytest.raises(zs.Invalid):
            zs.conform(bad, schema)
    with pytest.raises(zs.Invalid):
        zs.conform({}, {'$ref': '#'})  # self-reference cannot loop forever
    cat = {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name'],
           'additionalProperties': False}
    dog = {**cat, 'properties': {**cat['properties'], 'bark': {'type': 'boolean'}}}
    pets = {'anyOf': [cat, dog]}
    assert zs.conform({'name': 'rex', 'bark': True}, pets) == {'name': 'rex', 'bark': True}
    assert zs.conform({'name': 'tom', 'age': 3}, pets) == {'name': 'tom'}


def test_real_pydantic_schema_round_trip():
    pydantic = pytest.importorskip('pydantic')
    from typing import List, Optional

    class Node(pydantic.BaseModel):
        id: str
        name: str
        type: str
        description: str

    class Edge(pydantic.BaseModel):
        source_node_id: str
        target_node_id: str
        relationship_name: str
        description: Optional[str] = None

    class KnowledgeGraph(pydantic.BaseModel):
        nodes: List[Node] = pydantic.Field(..., default_factory=list)
        edges: List[Edge] = pydantic.Field(..., default_factory=list)

    req = cognee_request(KnowledgeGraph.model_json_schema())
    _, sp = zs.plan(req)
    assert sp['schema'] == KnowledgeGraph.model_json_schema()
    doc = zs.finish('```json\n%s\n```' % json.dumps(GRAPH), sp, 'big-pickle')
    KnowledgeGraph.model_validate_json(doc['choices'][0]['message']['content'])
    # instructor TOOLS mode: one tool call whose name matches and whose
    # arguments validate as the response model.
    forced = {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'x'}],
              'tools': [{'type': 'function', 'function': {'name': 'KnowledgeGraph', 'description': 'd',
                                                          'parameters': KnowledgeGraph.model_json_schema()}}],
              'tool_choice': {'type': 'function', 'function': {'name': 'KnowledgeGraph'}}}
    doc = zs.finish(json.dumps(GRAPH), zs.plan(forced)[1], 'big-pickle')
    calls = doc['choices'][0]['message']['tool_calls']
    assert len(calls) == 1 and calls[0]['function']['name'] == 'KnowledgeGraph'
    KnowledgeGraph.model_validate_json(calls[0]['function']['arguments'])


def test_tool_modes_produce_openai_tool_calls():
    forced = {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'x'}], 'tools': [TOOL],
              'tool_choice': {'type': 'function', 'function': {'name': 'KnowledgeGraph'}}}
    sp = zs.plan(forced)[1]
    for text in (json.dumps(GRAPH), json.dumps({'name': 'KnowledgeGraph', 'arguments': GRAPH})):
        doc = zs.finish(text, sp, 'big-pickle')
        choice = doc['choices'][0]
        assert choice['finish_reason'] == 'tool_calls' and choice['message']['content'] is None
        call_ = choice['message']['tool_calls'][0]
        assert call_['type'] == 'function' and call_['id'].startswith('call_')
        assert json.loads(call_['function']['arguments']) == GRAPH
        assert service_api._usable(doc)
    with pytest.raises(zs.Invalid):
        zs.finish(json.dumps({'nodes': 'nope'}), sp, 'm')
    other = {**TOOL, 'function': {'name': 'Other', 'parameters': {'type': 'object', 'properties': {
        'q': {'type': 'string'}}, 'required': ['q']}}}
    required = {**forced, 'tools': [TOOL, other], 'tool_choice': 'required'}
    doc = zs.finish('{"name": "Other", "arguments": {"q": "hi"}}', zs.plan(required)[1], 'm')
    assert doc['choices'][0]['message']['tool_calls'][0]['function'] == {'name': 'Other', 'arguments': '{"q":"hi"}'}
    with pytest.raises(zs.Invalid):
        zs.finish('{"q": "hi"}', zs.plan(required)[1], 'm')
    auto = {**forced, 'tool_choice': 'auto'}
    doc = zs.finish('No graph needed here.', zs.plan(auto)[1], 'm')
    assert doc['choices'][0]['message']['content'] == 'No graph needed here.'
    doc = zs.finish(json.dumps({'name': 'KnowledgeGraph', 'arguments': GRAPH}), zs.plan(auto)[1], 'm')
    assert doc['choices'][0]['finish_reason'] == 'tool_calls'


# ------------------------------------------- integration: _chat via fake CLI

def cli_state(tmp_path, answers, direct=None):
    """Zen CLI model big-pickle (2 keys, AA 90) + direct free b (AA 10) +
    escrowed paid pm. `answers(payload, n)` scripts the CLI text replies."""
    routes = [seed('opencode-zen', 'ONE'), seed('opencode-zen', 'TWO'), seed(),
              dict(seed('o', 'PAID', model='pm'), paid_eligibility=True)]
    s, clock = setup(tmp_path, routes)
    zen = free('big-pickle', 'opencode-zen')
    s.update_catalog('opencode-zen', [zen, *bridge_models([zen])])
    s.update_catalog('p', [free('b')])
    for c in s.connections():
        if c['protocol'] == 'zencli' or c['model'] in ('b', 'pm'):
            succeed(s, c)
    cli_calls = []

    def bridge_http(method, url, headers, payload):
        if url.endswith('/internal/catalog'):
            return HttpResponse(200, {}, b'{"ok":true}')
        cli_calls.append((headers['X-Keeper-Provider-Key'], payload))
        assert set(payload) <= {'model', 'messages', 'stream'} and not payload.get('stream')
        assert all(set(m) == {'role', 'content'} and isinstance(m['content'], str) and
                   m['role'] in ('system', 'user', 'assistant') for m in payload['messages'])
        text = answers(payload, len(cli_calls))
        return HttpResponse(200, {}, json.dumps({'id': 'chatcmpl-x', 'model': payload['model'], 'choices': [
            {'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
            'usage': {}, 'keeper_transport': 'zencli'}).encode())
    bridge = ZenCLI(s, 'synthetic-internal', bridge_http)
    direct_calls = []

    def direct_http(method, url, headers, payload):
        direct_calls.append(payload)
        if direct:
            return direct(payload)
        return HttpResponse(200, {}, json.dumps({'model': payload['model'], 'choices': [
            {'message': {'role': 'assistant', 'content': json.dumps(GRAPH)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 3}}).encode())
    selector = Selector(s, Sweeps(s, provider_interval=0, key_interval=0), RuntimeCredentials(routes).resolve,
                        verifier=lambda *a: Result('working'), config_builder=bridge.config)
    state = server.make_state('admin')
    state.update(availability=s, selector=selector, sweeps=selector.sweeps, zencli=bridge,
                 service_token='service', inference_transport=direct_http,
                 aa_scores={'big-pickle': 90, 'b': 10, 'pm': 50})
    return state, cli_calls, direct_calls


def serve(state, body):
    return call(state, 'POST', '/v1/chat/completions', body, {'Authorization': 'Bearer service'})


def zen_rows(state):
    return [c for c in state['availability'].connections() if c['protocol'] == 'zencli']


def assert_unpenalized(state):
    s = state['availability']
    for c in zen_rows(state):
        assert c['state'] == 'working' and not c['excluded'] and c['retry_at'] <= s.clock()
    assert not s.store.rows('SELECT * FROM av_feedback')


def test_cognee_request_is_served_by_the_free_cli_model(tmp_path):
    state, cli, direct = cli_state(tmp_path, lambda p, n: '```json\n%s\n```' % json.dumps(GRAPH))
    code, raw, headers = serve(state, {**cognee_request(), 'temperature': 0.0})
    assert code == 200, raw
    doc = json.loads(raw)
    assert json.loads(doc['choices'][0]['message']['content']) == GRAPH
    assert doc['model'] == 'big-pickle' and dict(headers)['X-Keeper-Model'] == 'big-pickle'
    assert len(cli) == 1 and not direct, 'CLI ranked before the direct/paid routes'
    assert b'synthetic-' not in raw
    row = state['availability'].store.rows('SELECT * FROM av_usage')[-1]
    assert (row['protocol'], row['outcome'], row['tokens_estimated']) == ('zencli', 'ok', 1)
    assert row['prompt_tokens'] > 0 and row['completion_tokens'] > 0


def test_invalid_answer_gets_one_repair_on_the_same_connection(tmp_path):
    bad = copy.deepcopy(GRAPH)
    del bad['edges'][0]['relationship_name']
    state, cli, direct = cli_state(tmp_path, lambda p, n: json.dumps(bad) if n == 1 else json.dumps(GRAPH))
    code, raw, _ = serve(state, cognee_request())
    assert code == 200 and json.loads(json.loads(raw)['choices'][0]['message']['content']) == GRAPH
    assert len(cli) == 2 and cli[0][0] == cli[1][0], 'repair reuses the same key'
    first, second = cli[0][1]['messages'], cli[1][1]['messages']
    assert second[:len(first)] == first
    assert second[-2] == {'role': 'assistant', 'content': json.dumps(bad)}
    assert 'relationship_name' in second[-1]['content'] and second[-1]['role'] == 'user'
    assert_unpenalized(state)
    checks = state['availability'].store.rows('SELECT state FROM av_checks WHERE kind=? ORDER BY id', ('serve',))
    assert [c['state'] for c in checks] == ['working']


def test_unsatisfiable_model_falls_through_without_key_penalty(tmp_path):
    state, cli, direct = cli_state(tmp_path, lambda p, n: 'I would rather describe it in prose.')
    code, raw, headers = serve(state, cognee_request())
    assert code == 200 and dict(headers)['X-Keeper-Model'] == 'b'
    assert len(cli) == 2, 'first answer + one repair, then the next model (not the other key)'
    assert len(direct) == 1 and direct[0]['response_format'] == {'type': 'json_object'}
    assert_unpenalized(state)
    checks = state['availability'].store.rows('SELECT state FROM av_checks WHERE kind=? ORDER BY id', ('serve',))
    assert [c['state'] for c in checks] == ['request_rejected', 'working']


def test_unsatisfied_cli_never_blocks_the_paid_fallback(tmp_path):
    def direct(payload):
        if payload['model'] == 'b':
            return HttpResponse(503, {}, b'{}')
        return HttpResponse(200, {}, json.dumps({'model': payload['model'], 'choices': [
            {'message': {'role': 'assistant', 'content': json.dumps(GRAPH)}, 'finish_reason': 'stop'}]}).encode())
    state, cli, calls = cli_state(tmp_path, lambda p, n: 'no json', direct)
    code, raw, headers = serve(state, cognee_request())
    assert code == 200 and dict(headers)['X-Keeper-Tier'] == 'paid'
    assert [p['model'] for p in calls][-1] == 'pm'
    assert_unpenalized(state)


def test_repair_is_skipped_when_the_deadline_is_near(tmp_path, monkeypatch):
    monkeypatch.setattr(service_api, 'REPAIR_MIN_REMAINING', 10 ** 6)
    state, cli, direct = cli_state(tmp_path, lambda p, n: 'no json here')
    code, _, headers = serve(state, cognee_request())
    assert code == 200 and len(cli) == 1 and dict(headers)['X-Keeper-Model'] == 'b'


def test_empty_cli_answer_is_still_provider_evidence(tmp_path):
    state, cli, direct = cli_state(tmp_path, lambda p, n: '   ')
    code, _, headers = serve(state, cognee_request())
    assert code == 200 and dict(headers)['X-Keeper-Model'] == 'b'
    assert len(cli) == 2, 'both keys tried: an empty answer is key/model evidence, as before'


def test_forced_tool_request_returns_tool_calls(tmp_path):
    state, cli, direct = cli_state(tmp_path, lambda p, n: json.dumps(GRAPH))
    code, raw, _ = serve(state, {'model': 'keeper-coder', 'messages': [
        {'role': 'system', 'content': 'Extract.'}, {'role': 'user', 'content': 'Cognee calls Keeper.'}],
        'tools': [TOOL], 'tool_choice': {'type': 'function', 'function': {'name': 'KnowledgeGraph'}},
        'temperature': 0, 'max_tokens': 1000})
    assert code == 200
    choice = json.loads(raw)['choices'][0]
    assert choice['finish_reason'] == 'tool_calls'
    assert json.loads(choice['message']['tool_calls'][0]['function']['arguments']) == GRAPH
    assert len(cli) == 1 and not direct


def test_streaming_structured_request_never_reaches_the_cli(tmp_path):
    state, cli, direct = cli_state(tmp_path, lambda p, n: json.dumps(GRAPH))
    state['stream_transport'] = lambda config, payload: iter(())
    serve(state, {**cognee_request(), 'stream': True})
    assert not cli


def test_plain_text_cli_request_payload_is_unchanged(tmp_path):
    state, cli, direct = cli_state(tmp_path, lambda p, n: 'Hello')
    body = {'model': 'keeper-coder', 'messages': [{'role': 'system', 'content': 'Be concise'},
                                                  {'role': 'user', 'content': 'Hi'}]}
    code, raw, _ = serve(state, body)
    assert code == 200 and json.loads(raw)['choices'][0]['message']['content'] == 'Hello'
    assert cli[0][1] == {**body, 'model': 'big-pickle'}
    assert 'keeper_emulation' not in json.loads(raw)


def test_real_go_sidecar_accepts_emulated_structured_requests(tmp_path):
    """The flattened payload passes the unchanged sidecar's strict decoder."""
    import functools
    import shutil
    import subprocess
    import tempfile
    import time
    from pathlib import Path
    import zencli_bridge
    from zencli_bridge import BRIDGE_BASE
    if not shutil.which('go'):
        pytest.skip('Go compiler unavailable')
    repo = Path(__file__).resolve().parent.parent
    binary, gate = tmp_path / 'zencli', tmp_path / 'sh'
    subprocess.run(['go', 'build', '-ldflags=-X main.clockShellPath=' + str(gate), '-o', str(binary), '.'],
                   cwd=repo / 'zencli', check=True, capture_output=True)
    gate.symlink_to(binary)
    events = tmp_path / 'events.jsonl'
    answer = 'Here you go:\n```json\n%s\n```' % json.dumps(GRAPH)
    events.write_text(json.dumps({'type': 'text', 'part': {'text': answer}}) + '\n'
                      + json.dumps({'type': 'step_finish', 'part': {'reason': 'stop'}}) + '\n')
    fake = tmp_path / 'opencode'
    fake.write_text('#!/bin/sh\n/bin/cat %s\n' % events)
    fake.chmod(0o700)
    ipc = tempfile.TemporaryDirectory(prefix='keeper-ipc-', dir='/tmp')
    socket_path = ipc.name + '/private/http.sock'
    process = subprocess.Popen([str(binary), '-socket', socket_path, '-opencode-bin', str(fake)],
                               env={'KEEPER_ZENCLI_TOKEN': 'synthetic-internal'},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        http = functools.partial(zencli_bridge.unix_request, socket_path=socket_path)
        for _ in range(50):
            try:
                if http('POST', BRIDGE_BASE.removesuffix('/v1') + '/internal/catalog', {}, {}).status == 401:
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError('sidecar did not start')
        state, _, direct = cli_state(tmp_path, lambda p, n: '')
        s = state['availability']
        s.clock.value = time.time()
        with s.store.transaction() as db:
            db.execute('UPDATE av_models SET checked_at=?', (s.clock(),))
            db.execute("UPDATE av_connections SET checked_at=? WHERE state='working'", (s.clock(),))
        state['zencli'].transport = http
        code, raw, headers = serve(state, {**cognee_request(), 'temperature': 0, 'max_tokens': 2048})
        assert code == 200 and dict(headers)['X-Keeper-Model'] == 'big-pickle', raw
        assert json.loads(json.loads(raw)['choices'][0]['message']['content']) == GRAPH
        code, raw, _ = serve(state, {'model': 'keeper-coder', 'tools': [TOOL], 'tool_choice': 'required', 'messages': [
            {'role': 'user', 'content': 'extract'},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_0', 'type': 'function', 'function': {
                'name': 'KnowledgeGraph', 'arguments': '{"nodes":[],"edges":[]}'}}]},
            {'role': 'tool', 'tool_call_id': 'call_0', 'content': 'too small, retry'}]})
        assert code == 200 and json.loads(raw)['choices'][0]['finish_reason'] == 'tool_calls', raw
        assert not direct and b'synthetic-' not in raw
    finally:
        process.terminate()
        process.wait(timeout=5)
        ipc.cleanup()
