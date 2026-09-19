/**
 * Bridge behavior tests (node:test, no framework).
 * Exercises runCli/streamZenCli directly: error, timeout, abort, success.
 * Run: npm test (node --test test/). Needs the opencode binary for
 * timeout/abort/success cases (OPENCODE_BIN, default PATH lookup).
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { runCli, streamZenCli } from "../index.ts";

const MODEL = { id: "mimo-v2.5-free", api: "zen-cli-api", provider: "zen-cli" };
// Machine under test: opencode lives outside PATH here (same as M1).
process.env.OPENCODE_BIN ??= "/Users/ksonny/.opencode/bin/opencode";
// Portable failing binary: node itself run against a bogus file -> exit 1.
const FAIL_BIN = process.execPath;
const CTX = (text) => ({ messages: [{ role: "user", content: text }] });

async function drain(stream) {
	const events = [];
	for await (const e of stream) events.push(e);
	return events;
}

describe("runCli error/timeout/abort", () => {
	it("error: failing binary rejects with code telemetry", async () => {
		process.env.OPENCODE_BIN = FAIL_BIN;
		await assert.rejects(() => runCli("opencode/x", "hi"), /code=1/);
		process.env.OPENCODE_BIN = "/Users/ksonny/.opencode/bin/opencode";
	});

	it("timeout: slow CLI is SIGTERM-killed with telemetry", async () => {
		process.env.ZEN_CLI_TIMEOUT_MS = "2000";
		await assert.rejects(
			() => runCli("opencode/mimo-v2.5-free", "Reply with exactly: TIMEOUT-PROBE"),
			/SIGTERM/,
		);
		delete process.env.ZEN_CLI_TIMEOUT_MS;
	});

	it("abort: AbortController kills the child and reports it", async () => {
		const ctl = new AbortController();
		setTimeout(() => ctl.abort(), 800);
		await assert.rejects(
			() => runCli("opencode/mimo-v2.5-free", "Reply with exactly: ABORT-PROBE", ctl.signal),
			/piAborted=true/,
		);
	});
});

describe("streamZenCli round-trip", () => {
	it("success: text comes back through the provider contract", async () => {
		const events = await drain(
			streamZenCli(MODEL, CTX("Reply with exactly: SPIKE-TEST-OK")),
		);
		const done = events.find((e) => e.type === "done");
		assert.ok(done, "expected a done event");
		const text = done.message.content.map((b) => b.text ?? "").join("");
		assert.match(text, /SPIKE-TEST-OK/);
	});

	it("error: failing binary ends the stream as error", async () => {
		process.env.OPENCODE_BIN = FAIL_BIN;
		const events = await drain(streamZenCli(MODEL, CTX("hi")));
		process.env.OPENCODE_BIN = "/Users/ksonny/.opencode/bin/opencode";
		const err = events.find((e) => e.type === "error");
		assert.ok(err, "expected an error event");
		assert.match(err.error.errorMessage ?? "", /code=1/);
	});
});
