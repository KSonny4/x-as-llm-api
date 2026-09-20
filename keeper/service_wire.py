"""Loss-aware OpenAI chat adapters for the service alias.

Native OpenAI requests pass through. Translated routes accept only explicitly
mapped fields and text/function-tool history; unsupported features make that
route incompatible, never silently dropped. Provider identity stays exact.
"""
import json
import translate

COMMON = {'model', 'messages', 'stream', 'max_tokens', 'max_completion_tokens',
          'temperature', 'top_p', 'stop', 'tools', 'tool_choice', 'stream_options'}
NATIVE = COMMON | {'response_format', 'parallel_tool_calls', 'n', 'seed',
                   'frequency_penalty', 'presence_penalty', 'logprobs', 'top_logprobs',
                   'logit_bias', 'user', 'reasoning_effort', 'verbosity'}


def safe_request(req):
    """No paid built-in tools/plugins, fallback models or provider overrides.

    A free model does not imply paid search/image/audio add-ons are free. The
    service executes no tools; ordinary client function schemas remain allowed.
    Unknown request extensions are rejected, never silently forwarded/dropped.
    """
    if set(req) - NATIVE:
        return False
    for msg in req.get('messages', []):
        if not isinstance(msg, dict) or set(msg) - {'role','content','tool_calls','tool_call_id','name'}:
            return False
        content = msg.get('content')
        if content is not None and not isinstance(content, str):
            if not isinstance(content, list) or any(not isinstance(p, dict) or set(p) != {'type','text'}
                    or p['type'] != 'text' or not isinstance(p['text'], str) for p in content):
                return False
        for tc in msg.get('tool_calls', []):
            if not isinstance(tc, dict) or set(tc) - {'id','type','function'} or tc.get('type') != 'function':
                return False
            if not isinstance(tc.get('function'), dict) or set(tc['function']) - {'name','arguments'}:
                return False
    tools = req.get('tools', [])
    if not isinstance(tools, list): return False
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) != {'type','function'} or tool['type'] != 'function':
            return False
        fn = tool['function']
        if not isinstance(fn, dict) or set(fn) - {'name','description','parameters','strict'} or not isinstance(fn.get('name'), str):
            return False
    choice = req.get('tool_choice')
    if choice is not None and choice not in ('auto','none','required'):
        if not isinstance(choice, dict) or set(choice) != {'type','function'} or choice['type'] != 'function':
            return False
        if not isinstance(choice['function'], dict) or set(choice['function']) != {'name'}:
            return False
    return True


def compatible(protocol, req):
    if not safe_request(req):
        return False
    if protocol == 'openai':
        return True
    if protocol not in ('anthropic', 'gemini', 'responses') or set(req) - COMMON:
        return False
    if req.get('stream_options') not in (None, {}, {'include_usage': False}):
        return False  # usage-inclusive translated streams are not yet lossless
    if protocol == 'responses' and req.get('stop') is not None:
        return False
    for message in req.get('messages', []):
        if set(message) - {'role', 'content', 'tool_calls', 'tool_call_id'}:
            return False
        if message.get('role') not in ('system', 'user', 'assistant', 'tool'):
            return False
        if message.get('content') is not None and not isinstance(message['content'], str):
            return False
        for call in message.get('tool_calls', []):
            try:
                if call['type'] != 'function' or not isinstance(json.loads(call['function']['arguments']), dict):
                    return False
            except (KeyError, TypeError, ValueError):
                return False
    for tool in req.get('tools', []):
        if tool.get('type') != 'function' or set(tool) - {'type', 'function'}:
            return False
        if set(tool.get('function', {})) - {'name', 'description', 'parameters'}:
            return False  # e.g. strict schema semantics require native support
    choice = req.get('tool_choice')
    if choice is not None and choice not in ('auto', 'none', 'required') and not (
            isinstance(choice, dict) and choice.get('type') == 'function' and
            isinstance(choice.get('function', {}).get('name'), str)):
        return False
    return True


def prepare(config, req):
    p = config['protocol']
    body = {**req, 'model': config['model']}
    limit = req.get('max_completion_tokens', req.get('max_tokens'))
    if p == 'openai':
        return body
    if p == 'anthropic':
        body = translate.openai_to_anthropic({**body, 'max_tokens': limit or 1024})
        for field in ('temperature', 'top_p'):
            if field in req: body[field] = req[field]
        if 'stop' in req:
            body['stop_sequences'] = [req['stop']] if isinstance(req['stop'], str) else req['stop']
        if req.get('tool_choice') in ('auto', 'none'):
            body['tool_choice'] = {'type': req['tool_choice']}
        return body
    if p == 'responses':
        inputs = []
        for m in req['messages']:
            if m['role'] == 'tool':
                inputs.append({'type': 'function_call_output', 'call_id': m['tool_call_id'], 'output': m['content']})
            else:
                if m.get('content') is not None:
                    inputs.append({'role': m['role'], 'content': m['content']})
                for tc in m.get('tool_calls', []):
                    inputs.append({'type': 'function_call', 'call_id': tc['id'], **tc['function']})
        body = {'model': config['model'], 'input': inputs, 'stream': bool(req.get('stream'))}
        if limit is not None: body['max_output_tokens'] = limit
        for field in ('temperature', 'top_p'):
            if field in req: body[field] = req[field]
        if 'tools' in req:
            body['tools'] = [{'type': 'function', **t['function']} for t in req['tools']]
        if 'tool_choice' in req:
            choice = req['tool_choice']
            body['tool_choice'] = {'type': 'function', 'name': choice['function']['name']} if isinstance(choice, dict) else choice
        return body
    contents, system, names = [], [], {}
    for m in req['messages']:
        if m['role'] == 'system':
            system.append({'text': m['content']}); continue
        parts = []
        if m['role'] == 'tool':
            name = names.get(m['tool_call_id'])
            if not name: raise ValueError('unmatched tool history')
            parts.append({'functionResponse': {'name': name, 'response': {'output': m['content']}}})
        else:
            if m.get('content'): parts.append({'text': m['content']})
            for tc in m.get('tool_calls', []):
                names[tc['id']] = tc['function']['name']
                parts.append({'functionCall': {'name': tc['function']['name'], 'args': json.loads(tc['function']['arguments'])}})
        contents.append({'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': parts})
    body = {'contents': contents, 'generationConfig': {}}
    if system: body['systemInstruction'] = {'parts': system}
    for old, new in [('temperature','temperature'), ('top_p','topP')]:
        if old in req: body['generationConfig'][new] = req[old]
    if limit is not None: body['generationConfig']['maxOutputTokens'] = limit
    if 'stop' in req: body['generationConfig']['stopSequences'] = [req['stop']] if isinstance(req['stop'], str) else req['stop']
    if req.get('tools'):
        body['tools'] = [{'functionDeclarations': [t['function'] for t in req['tools']]}]
    choice = req.get('tool_choice')
    if choice:
        fc = {'mode': {'auto':'AUTO', 'none':'NONE', 'required':'ANY'}.get(choice, 'ANY')} if isinstance(choice, str) else {'mode':'ANY', 'allowedFunctionNames':[choice['function']['name']]}
        body['toolConfig'] = {'functionCallingConfig': fc}
    return body


def exact(doc, config):
    if not isinstance(doc, dict) or 'error' in doc:
        raise ValueError('invalid upstream response')
    for field in ('model', 'modelVersion'):
        if doc.get(field) and doc[field] != config['model']:
            raise ValueError('model mismatch')


def completion(message, model, finish='stop', usage=None):
    return {'id': 'keeper-completion', 'object':'chat.completion', 'created':0, 'model':model,
            'choices':[{'index':0,'message':message,'finish_reason':finish}], 'usage':usage or {}}


def chunk(delta, model, finish=None):
    return {'id':'keeper-stream','object':'chat.completion.chunk','created':0,'model':model,
            'choices':[{'index':0,'delta':delta,'finish_reason':finish}]}


def gemini_message(doc):
    candidate = doc.get('candidates', [{}])[0]
    text, calls = [], []
    for part in candidate.get('content', {}).get('parts', []):
        if part.get('thought'): continue
        if 'text' in part: text.append(part['text'])
        if 'functionCall' in part:
            fc = part['functionCall']
            calls.append({'id':fc.get('id') or 'call_gemini_'+str(len(calls)), 'type':'function',
                          'function':{'name':fc['name'],'arguments':json.dumps(fc.get('args', {}))}})
    message = {'role':'assistant','content':''.join(text) or None}
    if calls: message['tool_calls'] = calls
    finish = candidate.get('finishReason')
    return message, ('tool_calls' if calls else 'length' if finish == 'MAX_TOKENS' else 'stop') if finish else None


def normalize(doc, config):
    exact(doc, config)
    p, model = config['protocol'], config['model']
    if p == 'openai': return doc
    if p == 'anthropic': return translate.anthropic_to_openai(doc, model)
    if p == 'gemini':
        msg, finish = gemini_message(doc)
        usage = doc.get('usageMetadata', {})
        return completion(msg, model, finish or 'stop', {'prompt_tokens':usage.get('promptTokenCount',0),
            'completion_tokens':usage.get('candidatesTokenCount',0), 'total_tokens':usage.get('totalTokenCount',0)})
    text, calls = [], []
    for item in doc.get('output', []):
        if item.get('type') == 'message':
            text.extend(part['text'] for part in item.get('content', []) if part.get('type') == 'output_text')
        elif item.get('type') == 'function_call':
            calls.append({'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':item['arguments']}})
    msg = {'role':'assistant','content':''.join(text) or None}
    if calls: msg['tool_calls'] = calls
    usage = doc.get('usage', {})
    return completion(msg, model, 'tool_calls' if calls else 'length' if doc.get('status')=='incomplete' else 'stop',
        {'prompt_tokens':usage.get('input_tokens',0),'completion_tokens':usage.get('output_tokens',0),'total_tokens':usage.get('total_tokens',0)})


def stream_chunks(events, config):
    p, model = config['protocol'], config['model']
    ended = False
    tool_indexes = {}
    for event in events:
        exact(event, config)
        out = None
        if p == 'openai':
            out = event
            ended |= any(c.get('finish_reason') for c in event.get('choices', []))
        elif p == 'anthropic':
            if event.get('type') == 'message_start': exact(event.get('message', {}), config)
            out = translate.anthropic_event_to_openai_chunk(event, model)
            if out and 'tool_calls' in out['choices'][0]['delta']:
                for tc in out['choices'][0]['delta']['tool_calls']:
                    idx = tc['index']; tool_indexes.setdefault(idx, len(tool_indexes)); tc['index'] = tool_indexes[idx]
            ended |= event.get('type') == 'message_stop'
        elif p == 'gemini':
            message, finish = gemini_message(event)
            for tc in message.get('tool_calls', []):
                tc['index'] = len(tool_indexes); tc['id'] = 'call_gemini_'+str(len(tool_indexes)); tool_indexes[tc['index']] = tc['index']
            out = chunk(message, model, finish)
            ended |= bool(finish)
        else:
            kind = event.get('type')
            if kind == 'response.output_text.delta': out = chunk({'content':event['delta']}, model)
            elif kind == 'response.output_item.added' and event.get('item', {}).get('type') == 'function_call':
                item=event['item'];idx=event['output_index'];tool_indexes[idx]=len(tool_indexes)
                out=chunk({'tool_calls':[{'index':tool_indexes[idx],'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':''}}]}, model)
            elif kind == 'response.function_call_arguments.delta':
                out=chunk({'tool_calls':[{'index':tool_indexes[event['output_index']],'function':{'arguments':event['delta']}}]}, model)
            elif kind in ('response.completed', 'response.incomplete'):
                exact(event.get('response', {}), config);ended=True
                out=chunk({},model,'length' if kind=='response.incomplete' else 'tool_calls' if tool_indexes else 'stop')
            elif kind in ('response.failed', 'error'): raise ValueError('upstream failed')
        if out is not None: yield out
    if not ended: raise ValueError('truncated upstream stream')
