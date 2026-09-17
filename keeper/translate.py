"""OpenAI-out translation (design §2 addendum).

Upstream wires stay internal: 'openai' passes through, 'anthropic' legs are
translated both ways so every consumer only ever speaks OpenAI. Pure
functions, stdlib only, no network.
"""

_STOP_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def openai_to_anthropic(req):
    """Map an OpenAI chat-completions request to an Anthropic messages body."""
    system_parts = []
    if req.get("system") is not None:
        system_parts.append(req["system"])
    messages = []
    for msg in req.get("messages", []):
        if not isinstance(msg, dict):
            messages.append(msg)
            continue
        if msg.get("role") == "system":
            # Standard OpenAI convention: system prompt lives in messages.
            # Anthropic wants it top-level instead.
            system_parts.append(msg.get("content", ""))
            continue
        messages.append(_openai_message_to_anthropic(msg))
    body = {
        "model": req["model"],
        "messages": messages,
        "max_tokens": req.get("max_tokens", 1024),
    }
    if system_parts:
        body["system"] = "\n".join(str(p) for p in system_parts)
    tools = req.get("tools") or []
    if tools:
        body["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {}),
            }
            for t in tools
            if t.get("type") == "function"
        ]
    choice = req.get("tool_choice")
    if choice == "required":
        body["tool_choice"] = {"type": "any"}
    elif isinstance(choice, dict):
        name = (choice.get("function") or {}).get("name",
                                                choice.get("name", ""))
        if name:
            body["tool_choice"] = {"type": "tool", "name": name}
    # "auto", "none", and absent: omit (Anthropic default).
    if req.get("stream"):
        body["stream"] = True
    return body


def _openai_message_to_anthropic(msg):
    """Map one OpenAI message to Anthropic shape (tool history included)."""
    tool_calls = msg.get("tool_calls") or []
    if tool_calls:
        blocks = []
        if msg.get("content"):
            blocks.append({"type": "text", "text": msg["content"]})
        for tc in tool_calls:
            fn = tc.get("function") or {}
            blocks.append({
                "type": "tool_use",
                "id": _strip_call_prefix(tc.get("id", "")),
                "name": fn.get("name", ""),
                "input": _json_loads(fn.get("arguments", "{}")),
            })
        return {"role": "assistant", "content": blocks}
    if msg.get("role") == "tool":
        return {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": _strip_call_prefix(msg.get("tool_call_id", "")),
            "content": msg.get("content", ""),
        }]}
    return {"role": msg.get("role"), "content": msg.get("content", "")}


def anthropic_to_openai(resp, model):
    """Map an Anthropic messages response to an OpenAI chat.completion."""
    text_parts = []
    tool_calls = []
    for block in resp.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": "call_%s" % block.get("id", "unknown"),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": _json_dumps(block.get("input", {})),
                },
            })
    message = {"role": "assistant",
               "content": "".join(text_parts) if text_parts else None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = resp.get("usage", {})
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    return {
        "id": resp.get("id", ""),
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _STOP_MAP.get(resp.get("stop_reason"), "stop"),
        }],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def anthropic_event_to_openai_chunk(event, model):
    """Map one Anthropic SSE event to an OpenAI chunk dict (or None to skip)."""
    etype = event.get("type")
    if etype == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            return _chunk(model, {"content": delta.get("text", "")}, None)
        if delta.get("type") == "input_json_delta":
            return _chunk(model, {"tool_calls": [{
                "index": event.get("index", 0),
                "function": {"arguments": delta.get("partial_json", "")},
            }]}, None)
        return None
    if etype == "content_block_start":
        # Anthropic sends tool id/name here; without this opening chunk the
        # later input_json_delta fragments are unassemblable per OpenAI
        # chunk convention (tool_calls entries need index+id+name).
        block = event.get("content_block", {})
        if block.get("type") == "tool_use":
            return _chunk(model, {"tool_calls": [{
                "index": event.get("index", 0),
                "id": "call_%s" % block.get("id", "unknown"),
                "type": "function",
                "function": {"name": block.get("name", ""),
                             "arguments": ""},
            }]}, None)
        return None
    if etype == "message_delta":
        delta = event.get("delta", {})
        reason = _STOP_MAP.get(delta.get("stop_reason"), "stop")
        return _chunk(model, {}, reason)
    if etype == "message_stop":
        # Terminal: finish_reason already arrived via message_delta, so
        # emitting another would duplicate it. Caller ends on [DONE].
        return None
    return None


def anthropic_error_to_openai(payload, status):
    """Map an Anthropic error payload to an OpenAI-shaped error."""
    inner = (payload or {}).get("error", {})
    return {
        "error": {
            "message": inner.get("message", "upstream error"),
            "type": inner.get("type", "upstream_error"),
            "code": inner.get("type", "upstream_error"),
        }
    }


def translate_to_openai(wire, payload, model):
    """Dispatch on upstream wire: 'openai' passes through untouched."""
    if wire == "openai":
        return payload
    if wire == "anthropic":
        return anthropic_to_openai(payload, model)
    raise ValueError("unknown wire: %r" % (wire,))


def _chunk(model, delta, finish_reason):
    return {
        "id": "",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta,
                     "finish_reason": finish_reason}],
    }


def _json_dumps(obj):
    import json
    return json.dumps(obj, separators=(",", ":"))


def _json_loads(text):
    import json
    try:
        return json.loads(text) if isinstance(text, str) else {}
    except Exception:
        return {}


def _strip_call_prefix(tid):
    # Inverse of anthropic_to_openai's "call_" prefix: recover the id the
    # upstream tool_use block carried so multi-turn round trips are stable.
    if isinstance(tid, str) and tid.startswith("call_"):
        return tid[len("call_"):]
    return tid
