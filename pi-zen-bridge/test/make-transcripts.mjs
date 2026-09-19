/**
 * Generates committed behavior transcripts (timeout / abort / error).
 * Run: node test/make-transcripts.mjs  (outputs to e2e-task/*-transcript.txt)
 * No secrets involved: failing/timeout paths never touch credentials.
 */
import { runCli } from "../index.ts";
import { writeFileSync } from "node:fs";

const OUT = new URL("../e2e-task/", import.meta.url);
process.env.OPENCODE_BIN ??= "/Users/ksonny/.opencode/bin/opencode";
const FAIL_BIN = process.execPath;

async function capture(name, fn) {
	const t0 = Date.now();
	const started = new Date().toISOString();
	let body;
	try {
		const v = await fn();
		body = `UNEXPECTED-RESOLVE: ${String(v).slice(0, 200)}`;
	} catch (e) {
		body = `rejected: ${e instanceof Error ? e.message : String(e)}`;
	}
	const elapsed = Date.now() - t0;
	const text = [
		`=== case: ${name}`,
		`=== started: ${started}`,
		`=== elapsed: ${elapsed}ms`,
		`--- result:`,
		body,
		``,
	].join("\n");
	writeFileSync(new URL(`${name}-transcript.txt`, OUT), text);
	console.log(`wrote ${name}-transcript.txt (${elapsed}ms)`);
}

await capture("timeout", () => {
	process.env.ZEN_CLI_TIMEOUT_MS = "2000";
	return runCli("opencode/mimo-v2.5-free", "Reply with exactly: TIMEOUT-PROBE").finally(() => {
		delete process.env.ZEN_CLI_TIMEOUT_MS;
	});
});

await capture("abort", () => {
	const ctl = new AbortController();
	setTimeout(() => ctl.abort(), 800);
	return runCli("opencode/mimo-v2.5-free", "Reply with exactly: ABORT-PROBE", ctl.signal);
});

await capture("error", () => {
	process.env.OPENCODE_BIN = FAIL_BIN;
	return runCli("opencode/x", "hi").finally(() => {
		process.env.OPENCODE_BIN = "/Users/ksonny/.opencode/bin/opencode";
	});
});
