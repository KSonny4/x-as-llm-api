"""Structured-output emulation for the genuine-CLI (zencli) route.

The CLI bridge only understands plain-text system/user/assistant turns and
returns plain text. This module lets `keeper-coder` still serve OpenAI
structured requests there, without touching the verified sidecar:

- `plan(req)` turns an OpenAI chat request into a bridge-legal text request:
  tool-call history is flattened into text turns, and a precise "reply with
  ONLY this JSON" instruction (JSON Schema, or function name + parameters) is
  appended to the last user turn.
- `finish(text, spec, model)` extracts the JSON from the CLI's text (fences
  and leading prose are tolerated), checks it against the schema with a small
  stdlib JSON-Schema subset validator, and rebuilds an OpenAI completion:
  `message.content` (response_format) or `message.tool_calls` (tools).
- `repair(payload, text, error)` builds the one self-correction turn.

Emulated shapes (see `spec`):
- response_format json_object (no schema; a schema the client embedded in its
  own prompt as "conforming to this schema: ```json ...```", which is what
  Cognee's litellm_native fallback sends, is detected and enforced too);
- response_format json_schema (the schema is enforced);
- tools with tool_choice forced to one function, "required", or "auto"/absent
  with exactly one tool; tool_choice "none" is plain text;
- OpenAI tool-call history (assistant tool_calls, tool results).

Generation controls the CLI cannot honour (IGNORED) are dropped, not
forwarded. Streaming, n>1, logprobs and logit_bias stay incompatible.
Never logs or returns prompt/answer text; validation errors name only paths.
"""
import copy
import json
import re
import secrets

# Accepted and ignored: the CLI takes no sampling/length/stop parameters.
IGNORED = frozenset({'temperature', 'top_p', 'max_tokens', 'max_completion_tokens', 'seed',
                     'frequency_penalty', 'presence_penalty', 'parallel_tool_calls', 'user',
                     'reasoning_effort', 'verbosity', 'stop'})
HANDLED = frozenset({'model', 'messages', 'stream', 'response_format', 'tools', 'tool_choice',
                     'n', 'logprobs'})
# The sidecar passes the whole flattened prompt as ONE argv element; Linux caps
# a single argument at 128 KiB (MAX_ARG_STRLEN). Stay well below it.
PROMPT_LIMIT = 120_000
REPAIR_ECHO_LIMIT = 24_000   # chars of the rejected answer echoed back
MAX_DEPTH = 128
_EMBEDDED_SCHEMA = re.compile(
    r'conform(?:s|ing)?\s+to\s+(?:this|the\s+following)\s+(?:json\s+)?schema\s*:?\s*'
    r'```(?:json)?[ \t]*\n(.*?)\n[ \t]*```', re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r'```(?:json|JSON)?[ \t]*\n?(.*?)```', re.DOTALL)


class Invalid(ValueError):
    """The model's answer does not satisfy the requested structure (yet)."""


class Unsatisfied(Exception):
    """After repair the model still cannot satisfy the request: try another
    model. Not credential evidence and not a malformed client request."""


# ---------------------------------------------------------------- request side

def _text(content):
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(p, dict) and p.get('type') == 'text'
                                         and isinstance(p.get('text'), str) for p in content):
        return ''.join(p['text'] for p in content)
    raise ValueError('non-text content')


def _compact(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False, sort_keys=False)


def _embedded_schema(messages):
    """A JSON Schema the client put in its own prompt (Cognee json fallback)."""
    for msg in reversed(messages):
        if msg.get('role') not in ('system', 'developer', 'user'):
            continue
        try:
            text = _text(msg.get('content'))
        except ValueError:
            continue
        for match in reversed(list(_EMBEDDED_SCHEMA.finditer(text))):
            try:
                schema = json.loads(match.group(1))
            except ValueError:
                continue
            if isinstance(schema, dict) and ('properties' in schema or '$defs' in schema
                                             or 'definitions' in schema or schema.get('type') == 'object'):
                return schema
    return None


def spec(req):
    """What the answer must look like; None for a plain-text request.

    Raises ValueError when the request cannot be emulated on the CLI route.
    """
    if not isinstance(req, dict) or set(req) - HANDLED - IGNORED:
        raise ValueError('unsupported field')
    if req.get('stream'):
        raise ValueError('streaming is not emulated')
    if req.get('n') not in (None, 1) or req.get('logprobs'):
        raise ValueError('unsupported generation feature')
    tools = [t for t in (req.get('tools') or []) if isinstance(t, dict)]
    if any(t.get('type') != 'function' or not isinstance(t.get('function'), dict) for t in tools):
        raise ValueError('non-function tool')
    choice = req.get('tool_choice')
    if choice == 'none':
        tools = []
    fmt = req.get('response_format') or {'type': 'text'}
    if not isinstance(fmt, dict):
        raise ValueError('invalid response_format')
    if tools:
        if fmt.get('type') != 'text':
            raise ValueError('tools and response_format together are not emulated')
        table = {}
        for tool in tools:
            fn = tool['function']
            params = fn.get('parameters') or {'type': 'object', 'properties': {}}
            if not isinstance(fn.get('name'), str) or not isinstance(params, dict):
                raise ValueError('invalid tool')
            table[fn['name']] = {'parameters': params, 'description': fn.get('description') or ''}
        if isinstance(choice, dict):
            name = choice['function']['name']
            if name not in table:
                raise ValueError('unknown forced tool')
            return {'kind': 'tool', 'mode': 'forced', 'tools': {name: table[name]}}
        if choice == 'required':
            return {'kind': 'tool', 'mode': 'required', 'tools': table}
        if choice in (None, 'auto') and len(table) == 1:
            return {'kind': 'tool', 'mode': 'auto', 'tools': table}
        raise ValueError('tool_choice not emulated')
    if fmt.get('type') == 'text':
        return None
    if fmt.get('type') == 'json_object':
        return {'kind': 'json', 'schema': _embedded_schema(req['messages']), 'name': None,
                'embedded': True}
    if fmt.get('type') == 'json_schema':
        schema = fmt['json_schema']
        return {'kind': 'json', 'schema': schema['schema'], 'name': schema.get('name'),
                'description': schema.get('description'), 'embedded': False}
    raise ValueError('unsupported response_format')


_RAW_ONLY = ('Output the raw JSON object only: no prose, no explanation, no markdown or code '
             'fences. Do not use any tools; answer directly from the conversation above.')


def instruction(sp):
    if sp['kind'] == 'json':
        if sp['schema'] is None:
            return 'Respond with ONLY a single valid JSON object. ' + _RAW_ONLY
        if sp.get('embedded'):
            return ('Respond with ONLY a single JSON object that conforms to the JSON Schema given '
                    'above. ' + _RAW_ONLY)
        name = (' named "%s"' % sp['name']) if sp.get('name') else ''
        described = ('\nSchema description: ' + sp['description']) if sp.get('description') else ''
        return ('Respond with ONLY a single JSON object%s that conforms to this JSON Schema:\n%s%s\n'
                % (name, _compact(sp['schema']), described) + _RAW_ONLY)
    tools = sp['tools']
    if sp['mode'] == 'forced':
        (name, tool), = tools.items()
        described = ('\nFunction description: ' + tool['description']) if tool['description'] else ''
        return ('You must call the function "%s". Respond with ONLY a single JSON object holding its '
                'arguments, conforming to this JSON Schema:\n%s%s\n'
                % (name, _compact(tool['parameters']), described) + _RAW_ONLY)
    listing = '\n'.join('- %s: %s\n  parameters JSON Schema: %s' % (
        name, tool['description'] or '(no description)', _compact(tool['parameters']))
        for name, tool in tools.items())
    call = ('Respond with ONLY a single JSON object of the form '
            '{"name": "<function name>", "arguments": {<arguments matching its parameters schema>}}. ')
    if sp['mode'] == 'required':
        return 'You must call exactly one of these functions:\n%s\n%s%s' % (listing, call, _RAW_ONLY)
    return ('You may call this function:\n%s\nIf calling it is the right next step, %s%s '
            'Otherwise answer normally in plain text without any JSON.'
            % (listing, call[0].lower() + call[1:], _RAW_ONLY))


def flatten(messages):
    """OpenAI history -> bridge-legal string system/user/assistant turns."""
    names, out = {}, []
    for msg in messages:
        role = msg.get('role')
        text = _text(msg.get('content'))
        if role == 'developer':
            role = 'system'
        if role == 'assistant' and msg.get('tool_calls'):
            calls = []
            for call in msg['tool_calls']:
                fn = call['function']
                names[call['id']] = fn['name']
                calls.append('[Called function %s (call id %s) with arguments: %s]'
                             % (fn['name'], call['id'], fn['arguments']))
            text = '\n'.join(([text] if text.strip() else []) + calls)
        elif role == 'tool':
            role = 'user'
            text = '[Result of function %s (call id %s)]:\n%s' % (
                names.get(msg.get('tool_call_id'), 'call'), msg.get('tool_call_id'), text)
        if role not in ('system', 'user', 'assistant'):
            raise ValueError('unsupported role')
        out.append({'role': role, 'content': text})
    return out


def cli_prompt_size(messages):
    """UTF-8 bytes of the sidecar's buildPrompt() output (upper bound)."""
    size = 0
    for m in messages:
        text = m['content'].strip() if isinstance(m.get('content'), str) else ''
        if text:
            size += len(text.encode('utf-8')) + len('Assistant: ') + 2
    return size


def plain(req):
    """True for requests the bridge already takes verbatim (unchanged path)."""
    return (not (set(req) - {'model', 'messages', 'stream'}) and not req.get('stream')
            and all(set(m) <= {'role', 'content'} and m.get('role') in ('system', 'user', 'assistant')
                    and isinstance(m.get('content'), str) for m in req['messages']))


def plan(req):
    """(bridge text request, spec). Raises ValueError when not emulatable."""
    sp = spec(req)
    if sp is None and plain(req):
        text_req = dict(req)
    else:
        messages = flatten(req['messages'])
        if sp is not None:
            note = instruction(sp)
            if messages and messages[-1]['role'] == 'user':
                messages[-1] = {'role': 'user', 'content': messages[-1]['content'].rstrip() + '\n\n' + note}
            else:
                messages.append({'role': 'user', 'content': note})
        text_req = {'model': req['model'], 'messages': messages}
    if cli_prompt_size(text_req['messages']) > PROMPT_LIMIT:
        raise ValueError('prompt too large for the CLI argument')
    if not any(isinstance(m.get('content'), str) and m['content'].strip() for m in text_req['messages']):
        raise ValueError('no prompt content')
    return text_req, sp


def supported(req):
    try:
        plan(req)
        return True
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def repair(payload, answer, error):
    """One self-correction turn on the same connection; None if too large."""
    echoed = answer if len(answer) <= REPAIR_ECHO_LIMIT else answer[:REPAIR_ECHO_LIMIT] + ' ...(truncated)'
    messages = list(payload['messages']) + [
        {'role': 'assistant', 'content': echoed.strip() or '(empty reply)'},
        {'role': 'user', 'content': (
            'Your previous reply was rejected: %s\nReply again with ONLY the corrected JSON, following '
            'the instructions above exactly. ' % str(error)[:1000]) + _RAW_ONLY}]
    body = {**payload, 'messages': messages}
    return body if cli_prompt_size(messages) <= PROMPT_LIMIT else None


# --------------------------------------------------------------- response side

def extract_json(text):
    """First JSON object in the text: whole text, fenced block, or embedded."""
    if not isinstance(text, str):
        raise Invalid('no text reply')
    stripped = text.strip()
    candidates = [stripped] + [m.group(1).strip() for m in _FENCE.finditer(stripped)]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    start, tries = stripped.find('{'), 0
    while start != -1 and tries < 256:
        tries += 1
        try:
            value, _ = decoder.raw_decode(stripped, start)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        start = stripped.find('{', start + 1)
    raise Invalid('the reply did not contain a JSON object')


def _resolve(ref, root):
    if not isinstance(ref, str) or not ref.startswith('#'):
        raise Invalid('unsupported $ref')
    node = root
    for part in [p for p in ref[1:].split('/') if p]:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise Invalid('unresolvable $ref')
    return node


_TYPES = {
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'string': lambda v: isinstance(v, str),
    'boolean': lambda v: isinstance(v, bool),
    'null': lambda v: v is None,
    'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    'integer': lambda v: (isinstance(v, int) and not isinstance(v, bool)
                          or isinstance(v, float) and v.is_integer()),
}


def _where(path):
    return path or '$'


def conform(value, schema, root=None, path='$', depth=0):
    """Validate `value` against a JSON-Schema subset; return a pruned copy.

    Supported: $ref (local, incl. $defs/definitions), type (incl. lists),
    enum, const, properties, required, additionalProperties (false prunes
    extras, like pydantic's default extra='ignore'; a schema validates them),
    items, min/maxItems, min/maxLength, minimum/maximum (+exclusive),
    anyOf/oneOf (first matching branch), allOf. Unknown keywords are ignored
    (lenient: the client revalidates). Raises Invalid naming the path.
    """
    root = schema if root is None else root
    if depth > MAX_DEPTH:
        raise Invalid('schema nesting too deep at %s' % path)
    if schema is True or schema == {} or schema is None:
        return value
    if schema is False:
        raise Invalid('%s is not allowed' % path)
    if not isinstance(schema, dict):
        return value
    if '$ref' in schema:
        target = _resolve(schema['$ref'], root)
        value = conform(value, target, root, path, depth + 1)
    for branch in schema.get('allOf') or []:
        value = conform(value, branch, root, path, depth + 1)
    for keyword in ('anyOf', 'oneOf'):
        branches = schema.get(keyword)
        if isinstance(branches, list) and branches:
            # Prefer a branch that fits without pruning: a looser sibling must
            # not silently drop fields that belong to a later alternative.
            errors, pruned = [], None
            for branch in branches:
                try:
                    result = conform(copy.deepcopy(value), branch, root, path, depth + 1)
                except Invalid as exc:
                    errors.append(str(exc))
                    continue
                if result == value:
                    break
                pruned = [result] if pruned is None else pruned
            else:
                if pruned is None:
                    raise Invalid('%s matches none of the allowed alternatives (%s)'
                                  % (path, '; '.join(errors[:3])[:600]))
                value = pruned[0]
    kinds = schema.get('type')
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_TYPES.get(k, lambda v: True)(value) for k in kinds):
            raise Invalid('%s must be of type %s' % (path, ' or '.join(map(str, kinds))))
    if 'enum' in schema and isinstance(schema['enum'], list) and value not in schema['enum']:
        raise Invalid('%s must be one of %s' % (path, _compact(schema['enum'])[:300]))
    if 'const' in schema and value != schema['const']:
        raise Invalid('%s must equal %s' % (path, _compact(schema['const'])[:200]))
    if isinstance(value, str):
        if isinstance(schema.get('minLength'), int) and len(value) < schema['minLength']:
            raise Invalid('%s is shorter than %d characters' % (path, schema['minLength']))
        if isinstance(schema.get('maxLength'), int) and len(value) > schema['maxLength']:
            raise Invalid('%s is longer than %d characters' % (path, schema['maxLength']))
    if _TYPES['number'](value):
        for key, bad in (('minimum', lambda v, b: v < b), ('maximum', lambda v, b: v > b),
                         ('exclusiveMinimum', lambda v, b: v <= b), ('exclusiveMaximum', lambda v, b: v >= b)):
            bound = schema.get(key)
            if _TYPES['number'](bound) and bad(value, bound):
                raise Invalid('%s violates %s %s' % (path, key, bound))
    if isinstance(value, list):
        if isinstance(schema.get('minItems'), int) and len(value) < schema['minItems']:
            raise Invalid('%s needs at least %d items' % (path, schema['minItems']))
        if isinstance(schema.get('maxItems'), int) and len(value) > schema['maxItems']:
            raise Invalid('%s allows at most %d items' % (path, schema['maxItems']))
        items = schema.get('items')
        if isinstance(items, dict):
            value = [conform(item, items, root, '%s[%d]' % (path, i), depth + 1)
                     for i, item in enumerate(value)]
    if isinstance(value, dict):
        props = schema.get('properties') if isinstance(schema.get('properties'), dict) else {}
        for key in schema.get('required') or []:
            if key not in value:
                raise Invalid('%s is missing required property "%s"' % (path, key))
        extra = schema.get('additionalProperties', True)
        result = {}
        for key, item in value.items():
            where = '%s.%s' % (path, key)
            if key in props:
                result[key] = conform(item, props[key], root, where, depth + 1)
            elif extra is False:
                continue  # pruned, not an error (pydantic ignores extras by default)
            elif isinstance(extra, dict):
                result[key] = conform(item, extra, root, where, depth + 1)
            else:
                result[key] = item
        value = result
    return value


def finish(text, sp, model, usage=None):
    """CLI text -> OpenAI chat.completion for the spec. Raises Invalid."""
    if sp['kind'] == 'json':
        obj = extract_json(text)
        if sp['schema'] is not None:
            obj = conform(obj, sp['schema'])
        return _completion({'role': 'assistant', 'content': _compact(obj)}, model, 'stop', usage)
    tools = sp['tools']
    if sp['mode'] == 'auto':
        try:
            obj = extract_json(text)
        except Invalid:
            obj = None
        name = obj.get('name') if isinstance(obj, dict) else None
        if not (isinstance(name, str) and name in tools and isinstance(obj.get('arguments'), (dict, str))):
            if not isinstance(text, str) or not text.strip():
                raise Invalid('empty reply')
            return _completion({'role': 'assistant', 'content': text}, model, 'stop', usage)
        return _tool_call(name, obj['arguments'], tools, model, usage)
    obj = extract_json(text)
    if sp['mode'] == 'forced':
        (name, tool), = tools.items()
        props = tool['parameters'].get('properties') or {}
        # Tolerate a {"name","arguments"} envelope unless those are real fields.
        if (set(obj) == {'name', 'arguments'} and obj['name'] == name
                and 'arguments' not in props and 'name' not in props):
            return _tool_call(name, obj['arguments'], tools, model, usage)
        return _tool_call(name, obj, tools, model, usage)
    name = obj.get('name')
    if isinstance(name, str) and name in tools and 'arguments' in obj:
        return _tool_call(name, obj['arguments'], tools, model, usage)
    if len(tools) == 1 and not (isinstance(name, str) and 'arguments' in obj):
        (only,) = tools
        return _tool_call(only, obj, tools, model, usage)
    raise Invalid('reply must be {"name": one of %s, "arguments": {...}}' % _compact(sorted(tools))[:300])


def _tool_call(name, arguments, tools, model, usage):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            raise Invalid('function arguments are not valid JSON')
    if not isinstance(arguments, dict):
        raise Invalid('function arguments must be a JSON object')
    arguments = conform(arguments, tools[name]['parameters'])
    call = {'id': 'call_' + secrets.token_hex(12), 'type': 'function',
            'function': {'name': name, 'arguments': _compact(arguments)}}
    return _completion({'role': 'assistant', 'content': None, 'tool_calls': [call]}, model, 'tool_calls', usage)


def _completion(message, model, finish_reason, usage):
    return {'id': 'keeper-completion', 'object': 'chat.completion', 'created': 0, 'model': model,
            'choices': [{'index': 0, 'message': message, 'finish_reason': finish_reason}],
            'usage': usage if isinstance(usage, dict) else {}, 'keeper_emulation': 'structured'}


def reply_text(doc):
    """The CLI bridge's single text answer."""
    try:
        text = doc['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return None
    return text if isinstance(text, str) else None
