import json
from unittest.mock import patch
import server
from availability import Model, Result
from inference import HttpResponse
from test_api_v2 import state_for, call
from test_availability import free, succeed


def service_call(state, path, data=None):
    return call(state, 'POST' if data is not None else 'GET', path, data, {'Authorization': 'Bearer service'})


def ready(tmp_path):
    state, calls = state_for(tmp_path)
    for cell in state['availability'].connections(): succeed(state['availability'], cell)
    state['aa_scores'] = {'a': 10, 'b': 90}
    return state


def test_service_nonexpiring_allowlist_and_no_provider_keys(tmp_path):
    state = ready(tmp_path)
    with patch('server.time.time', return_value=9999999999):
        code, raw, _ = service_call(state, '/v1/models')
    assert code == 200 and [m['id'] for m in json.loads(raw)['data']] == ['keeper-coder']
    for path in ['/', '/packs', '/api/v2/catalog', '/v1/route/a', '/metrics', '/api/v1/matrix']:
        assert service_call(state, path)[0] == 403
    for path in ['/api/v1/session', '/api/v2/credentials', '/api/v2/checks', '/api/v2/feedback', '/feedback']:
        assert service_call(state, path, {})[0] == 403
    assert b'synthetic-secret' not in raw


def test_ranked_alias_nonstream_tools_pass_through_without_quota(tmp_path):
    state = ready(tmp_path); seen=[]
    def http(method,url,headers,payload):
        seen.append(payload)
        return HttpResponse(200, {}, json.dumps({'model':payload['model'],'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function','function':{'name':'edit','arguments':'{}'}}]},'finish_reason':'tool_calls','index':0}]}).encode())
    state['inference_transport']=http
    req={'model':'keeper-coder','messages':[{'role':'user','content':'edit'}], 'tools':[{'type':'function','function':{'name':'edit','parameters':{'type':'object'}}}], 'tool_choice':'required'}
    for _ in range(5):
        code,raw,_=service_call(state,'/v1/chat/completions',req)
        assert code == 200 and json.loads(raw)['choices'][0]['message']['tool_calls'][0]['id']=='call_1'
    assert len(seen)==5 and all(p['model']=='b' and p['tools']==req['tools'] for p in seen)
    assert b'synthetic-secret' not in raw


def test_bounded_ranked_failover_and_precise_feedback(tmp_path):
    state=ready(tmp_path); seen=[]
    def http(method,url,headers,payload):
        seen.append(payload['model'])
        if payload['model']=='b':return HttpResponse(500, {}, b'{"error":"synthetic-secret"}')
        return HttpResponse(200, {}, json.dumps({'model':'a','choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]}).encode())
    state['inference_transport']=http
    code,raw,_=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}]})
    assert code==200 and seen==['b','b','a']
    failed=[c for c in state['availability'].connections() if c['excluded']]
    assert len(failed)==2 and all(c['model']=='b' for c in failed)
    assert state['availability'].feedback(failed[0]['id'])
    assert b'synthetic-secret' not in raw


def test_stream_is_real_incremental_and_never_retries_after_output(tmp_path):
    state=ready(tmp_path); seen=[]
    def stream(config,payload):
        seen.append(payload['model'])
        yield {'model':payload['model'],'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'call_1','type':'function','function':{'name':'edit','arguments':''}}]},'finish_reason':None}]}
        yield {'model':payload['model'],'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':'{}'}}]},'finish_reason':None}]}
        raise OSError('synthetic-secret')
    state['stream_transport']=stream
    code,body,headers=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}],'stream':True})
    assert code==200 and not isinstance(body,bytes)
    chunks=iter(body);first=next(chunks)
    assert b'call_1' in first and len(seen)==1
    raw=first+b''.join(chunks)
    assert b'arguments' in raw and b'upstream_failed' in raw and b'synthetic-secret' not in raw and len(seen)==1


def test_no_paid_unknown_or_incompatible_spend(tmp_path):
    state=ready(tmp_path)
    s=state['availability'];s.update_catalog('p',[Model('p','b','https://example.test/v1','openai','paid','public'),free('a')])
    seen=[]
    state['inference_transport']=lambda *a: seen.append(a) or HttpResponse(500,{},b'{}')
    code,raw,_=service_call(state,'/v1/chat/completions',{'model':'another','messages':[]})
    assert code==400 and not seen
    code,raw,_=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}]})
    assert all(args[3]['model']=='a' for args in seen) and len(seen)<=3
    assert b'synthetic-secret' not in raw


def test_stream_failure_before_first_event_falls_back(tmp_path):
    state=ready(tmp_path); seen=[]
    def stream(config,payload):
        seen.append(config['model'])
        if config['model']=='b':raise OSError('private error')
        yield {'model':'a','choices':[{'index':0,'delta':{'content':'hello'},'finish_reason':None}]}
        yield {'model':'a','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
    state['stream_transport']=stream
    code,body,_=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}],'stream':True})
    assert code==200 and b'hello' in b''.join(body) and seen==['b','b','a']


def test_wire_tools_and_streams_across_all_protocols():
    import service_wire as w
    request={'model':'keeper-coder','messages':[{'role':'user','content':'hello'}], 'tools':[{'type':'function','function':{'name':'edit','parameters':{'type':'object'}}}], 'tool_choice':'required','stream':True}
    docs={
      'anthropic': {'model':'exact','content':[{'type':'tool_use','id':'abc','name':'edit','input':{'x':1}}], 'stop_reason':'tool_use'},
      'gemini': {'modelVersion':'exact','candidates':[{'content':{'parts':[{'functionCall':{'name':'edit','args':{'x':1}}}]},'finishReason':'STOP'}]},
      'responses': {'model':'exact','output':[{'type':'function_call','call_id':'abc','name':'edit','arguments':'{"x":1}'}]},
    }
    events={
      'anthropic': [{'type':'message_start','message':{'model':'exact'}},{'type':'content_block_start','index':1,'content_block':{'type':'tool_use','id':'abc','name':'edit'}},{'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'{"x":1}'}},{'type':'message_delta','delta':{'stop_reason':'tool_use'}},{'type':'message_stop'}],
      'gemini':[docs['gemini']],
      'responses':[{'type':'response.output_item.added','output_index':1,'item':{'type':'function_call','call_id':'abc','name':'edit'}},{'type':'response.function_call_arguments.delta','output_index':1,'delta':'{"x":1}'},{'type':'response.completed','response':{'model':'exact'}}]
    }
    for protocol in docs:
        config={'model':'exact','protocol':protocol}
        assert w.compatible(protocol,request)
        assert w.prepare(config,request)
        result=w.normalize(docs[protocol],config)
        assert json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments'])=={'x':1}
        chunks=list(w.stream_chunks(iter(events[protocol]),config))
        toolchunks=[tc for chunk in chunks for tc in chunk['choices'][0]['delta'].get('tool_calls',[])]
        assert toolchunks[0]['index']==0 and toolchunks[0]['function']['name']=='edit'
        assert any(chunk['choices'][0]['finish_reason']=='tool_calls' for chunk in chunks)
        assert not w.compatible(protocol,{**request,'response_format':{'type':'json_object'}})


def test_translated_request_features_not_silently_dropped():
    import service_wire as w
    req={'model':'keeper-coder','messages':[{'role':'user','content':'hello'}],'temperature':0.2,'top_p':0.9,'stop':['END'],'max_completion_tokens':42,'tool_choice':'none'}
    anth=w.prepare({'model':'a','protocol':'anthropic'},req)
    assert anth['temperature']==0.2 and anth['top_p']==0.9 and anth['max_tokens']==42 and anth['stop_sequences']==['END'] and anth['tool_choice']=={'type':'none'}
    gem=w.prepare({'model':'a','protocol':'gemini'},req)
    assert gem['generationConfig']=={'temperature':0.2,'topP':0.9,'stopSequences':['END'],'maxOutputTokens':42}
    assert not w.compatible('responses',req)


def test_spend_and_fallback_extensions_rejected_before_any_inference(tmp_path):
    state=ready(tmp_path);seen=[]
    state['inference_transport']=lambda *a:seen.append(a)
    base={'model':'keeper-coder','messages':[{'role':'user','content':'hello'}]}
    for extension in [{'plugins':[{'id':'web','engine':'exa'}]}, {'models':['paid/fallback']}, {'provider':{'allow_fallbacks':True}}, {'route':'fallback'}, {'tools':[{'type':'web_search_preview'}]}]:
        code,raw,_=service_call(state,'/v1/chat/completions',{**base,**extension})
        assert code==400 and json.loads(raw)['error']['code']=='unsupported_request_features'
    assert not seen


def test_empty_stream_does_not_become_working_and_falls_back_before_output(tmp_path):
    state=ready(tmp_path);seen=[]
    def stream(config,payload):
        seen.append(config['model'])
        yield {'model':config['model'],'choices':[{'index':0,'delta':{'role':'assistant'},'finish_reason':None}]}
        if config['model']=='a':
            yield {'model':'a','choices':[{'index':0,'delta':{'content':'Hello'},'finish_reason':None}]}
        yield {'model':config['model'],'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
    state['stream_transport']=stream
    before=len(state['availability'].store.rows('SELECT * FROM av_checks'))
    code,body,_=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}],'stream':True})
    assert code==200 and b'Hello' in b''.join(body)
    assert seen==['b','b','a']
    checks=state['availability'].store.rows('SELECT * FROM av_checks ORDER BY id')[before:]
    assert [c['state'] for c in checks]==['invalid_response','invalid_response','working']


def test_same_strongest_model_alternative_precedes_weaker(tmp_path):
    state=ready(tmp_path);seen=[]
    def http(method,url,headers,payload):
        seen.append((payload['model'],headers['Authorization']))
        if len(seen)==1:return HttpResponse(500,{},b'{}')
        return HttpResponse(200,{},json.dumps({'model':payload['model'],'choices':[{'message':{'content':'Hello'}}]}).encode())
    state['inference_transport']=http
    code,raw,_=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}]})
    assert code==200 and [x[0] for x in seen]==['b','b'] and seen[0][1]!=seen[1][1]


def test_admin_exact_gateway_uses_verified_free_route_without_cli_spoof(tmp_path):
    state=ready(tmp_path);seen=[]
    def http(method,url,headers,payload):
        seen.append((headers,payload))
        return HttpResponse(200,{},json.dumps({'model':payload['model'],'choices':[{'message':{'content':'Hello'}}]}).encode())
    state['inference_transport']=http
    code,body,_=call(state,'POST','/v1/chat/completions',{'model':'a','messages':[{'role':'user','content':'hello'}]})
    assert code==200 and seen[0][1]['model']=='a'
    assert all(not k.lower().startswith('x-opencode') for k in seen[0][0])
    state['availability'].update_catalog('p',[free('b')])
    assert call(state,'POST','/v1/chat/completions',{'model':'a','messages':[{'role':'user','content':'hello'}]})[0]==503
    assert len(seen)==1


def test_same_model_spare_after_stale_success_revalidation_failure(tmp_path):
    state=ready(tmp_path)
    state['availability'].clock.advance(301)
    probes=[]
    def verify_http(method,url,headers,payload):
        probes.append(payload['model'])
        if len(probes)==1:return HttpResponse(500,{},b'{}')
        return HttpResponse(200,{},json.dumps({'model':payload['model'],'choices':[{'message':{'content':'Hello'}}]}).encode())
    state['selector'].transport=verify_http
    state['inference_transport']=lambda method,url,headers,payload: HttpResponse(200,{},json.dumps({'model':payload['model'],'choices':[{'message':{'content':'Hello'}}]}).encode())
    code,raw,_=service_call(state,'/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'hello'}]})
    assert code==200 and json.loads(raw)['model']=='b' and probes==['b','b']
