"""Fixture tests for keeper/translate.py (no live calls).

Wire contract (design §2 addendum OpenAI-out):
- wire 'openai' passes through untouched.
- wire 'anthropic' translates both ways.
"""
import unittest

from translate import (
    anthropic_error_to_openai,
    anthropic_event_to_openai_chunk,
    anthropic_to_openai,
    openai_to_anthropic,
    translate_to_openai,
)


class OpenAITranslatorTests(unittest.TestCase):
    def test_request_maps_system_messages_tools(self):
        req = {
            "model": "muse",
            "system": "be terse",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 16,
            "tools": [{
                "type": "function",
                "function": {"name": "get_time", "description": "now",
                             "parameters": {"type": "object", "properties": {}}},
            }],
            "tool_choice": "auto",
        }
        body = openai_to_anthropic(req)
        self.assertEqual(body["model"], "muse")
        self.assertEqual(body["system"], "be terse")
        self.assertEqual(body["max_tokens"], 16)
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(body["tools"][0]["name"], "get_time")
        self.assertIn("input_schema", body["tools"][0])

    def test_request_without_system_or_tools(self):
        body = openai_to_anthropic({
            "model": "m", "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        })
        self.assertNotIn("system", body)
        self.assertNotIn("tools", body)
        self.assertEqual(body["max_tokens"], 8)

    def test_response_text_and_usage(self):
        resp = {
            "id": "msg_1", "model": "muse", "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
        out = anthropic_to_openai(resp, "muse")
        self.assertEqual(out["object"], "chat.completion")
        self.assertEqual(out["model"], "muse")
        choice = out["choices"][0]
        self.assertEqual(choice["message"]["content"], "hello")
        self.assertEqual(choice["finish_reason"], "stop")
        self.assertEqual(out["usage"],
                         {"prompt_tokens": 5, "completion_tokens": 3,
                          "total_tokens": 8})

    def test_response_tool_use_gets_ids(self):
        resp = {
            "id": "msg_2", "model": "muse", "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_1",
                         "name": "get_time", "input": {}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 9, "output_tokens": 4},
        }
        out = anthropic_to_openai(resp, "muse")
        msg = out["choices"][0]["message"]
        self.assertIsNone(msg["content"])
        self.assertEqual(len(msg["tool_calls"]), 1)
        tc = msg["tool_calls"][0]
        self.assertEqual(tc["type"], "function")
        self.assertTrue(tc["id"])
        self.assertEqual(tc["function"]["name"], "get_time")
        self.assertEqual(tc["function"]["arguments"], "{}")
        self.assertEqual(out["choices"][0]["finish_reason"], "tool_calls")

    def test_stop_reason_mapping(self):
        for anthropic_reason, openai_reason in [
                ("end_turn", "stop"), ("max_tokens", "length"),
                ("tool_use", "tool_calls"), ("stop_sequence", "stop")]:
            resp = {"id": "m", "model": "m", "content": [],
                    "stop_reason": anthropic_reason,
                    "usage": {"input_tokens": 1, "output_tokens": 1}}
            out = anthropic_to_openai(resp, "m")
            self.assertEqual(out["choices"][0]["finish_reason"],
                             openai_reason, anthropic_reason)

    def test_stream_text_delta_chunk(self):
        chunk = anthropic_event_to_openai_chunk(
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "hi"}},
            "muse")
        self.assertEqual(chunk["object"], "chat.completion.chunk")
        self.assertEqual(chunk["choices"][0]["delta"],
                         {"content": "hi"})
        self.assertEqual(chunk["choices"][0]["finish_reason"], None)

    def test_stream_message_delta_finish(self):
        chunk = anthropic_event_to_openai_chunk(
            {"type": "message_delta",
             "delta": {"stop_reason": "tool_use"}}, "muse")
        self.assertEqual(chunk["choices"][0]["finish_reason"],
                         "tool_calls")
        self.assertEqual(chunk["choices"][0]["delta"], {})

    def test_stream_message_stop_ignored(self):
        # Finish already arrived via message_delta; message_stop must not
        # duplicate it (caller ends the stream on [DONE]).
        self.assertIsNone(
            anthropic_event_to_openai_chunk({"type": "message_stop"},
                                            "muse"))

    def test_stream_ignorable_events(self):
        for ev in [{"type": "ping"},
                   {"type": "message_start", "message": {"id": "msg_1"}}]:
            self.assertIsNone(
                anthropic_event_to_openai_chunk(ev, "muse"), ev["type"])

    def test_error_shape(self):
        err = anthropic_error_to_openai(
            {"type": "error",
             "error": {"type": "overloaded_error",
                       "message": "busy"}}, 429)
        self.assertEqual(err["error"]["message"], "busy")
        self.assertEqual(err["error"]["code"], "overloaded_error")
        self.assertIn("error", err)
        self.assertNotIn("status", err["error"])

    def test_openai_wire_passthrough(self):
        payload = {"id": "chatcmpl-1", "choices": []}
        self.assertIs(translate_to_openai("openai", payload, "m"), payload)

    def test_anthropic_wire_uses_translator(self):
        resp = {"id": "msg_9", "model": "m",
                "content": [{"type": "text", "text": "yo"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 2, "output_tokens": 1}}
        out = translate_to_openai("anthropic", resp, "m")
        self.assertEqual(out["object"], "chat.completion")
        self.assertEqual(out["choices"][0]["message"]["content"], "yo")

    def test_system_role_in_messages_extracted(self):
        body = openai_to_anthropic({
            "model": "m",
            "messages": [{"role": "system", "content": "be terse"},
                           {"role": "user", "content": "hi"}],
        })
        self.assertEqual(body["system"], "be terse")
        self.assertEqual(body["messages"],
                         [{"role": "user", "content": "hi"}])

    def test_tool_history_round_trip(self):
        body = openai_to_anthropic({
            "model": "m",
            "messages": [
                {"role": "assistant", "content": None,
                 "tool_calls": [{"id": "call_toolu_1",
                                  "type": "function",
                                  "function": {"name": "get_time",
                                               "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call_toolu_1",
                 "content": "noon"},
            ],
        })
        self.assertEqual(body["messages"][0],
                         {"role": "assistant", "content": [{
                             "type": "tool_use", "id": "toolu_1",
                             "name": "get_time", "input": {}}]})
        self.assertEqual(body["messages"][1],
                         {"role": "user", "content": [{
                             "type": "tool_result",
                             "tool_use_id": "toolu_1",
                             "content": "noon"}]})

    def test_stream_tool_use_start_chunk(self):
        chunk = anthropic_event_to_openai_chunk(
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "toolu_7",
                               "name": "get_time", "input": {}}},
            "muse")
        tc = chunk["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual(tc["index"], 1)
        self.assertEqual(tc["id"], "call_toolu_7")
        self.assertEqual(tc["function"]["name"], "get_time")
        self.assertEqual(tc["function"]["arguments"], "")
        self.assertIsNone(chunk["choices"][0]["finish_reason"])

    def test_tool_choice_mapping(self):
        base = {"model": "m",
                "messages": [{"role": "user", "content": "hi"}]}
        req = dict(base, tool_choice="required")
        self.assertEqual(openai_to_anthropic(req)["tool_choice"],
                         {"type": "any"})
        req = dict(base, tool_choice={"type": "function",
                                      "function": {"name": "get_time"}})
        self.assertEqual(openai_to_anthropic(req)["tool_choice"],
                         {"type": "tool", "name": "get_time"})
        for drop in ("auto", "none"):
            req = dict(base, tool_choice=drop)
            self.assertNotIn("tool_choice", openai_to_anthropic(req))

    def test_unknown_wire_raises(self):
        with self.assertRaises(ValueError):
            translate_to_openai("grpc", {}, "m")

    def test_stream_flag_propagated(self):
        body = openai_to_anthropic({
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        })
        self.assertTrue(body["stream"])


if __name__ == "__main__":
    unittest.main()
