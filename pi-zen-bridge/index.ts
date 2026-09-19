/**
 * pi-zen-bridge (M1 SPIKE, not production).
 *
 * Registers a pi provider ("zen-cli") whose completions shell out to the
 * local `opencode` CLI instead of HTTP, so FREE Zen keys (403 over direct
 * HTTP — FreeTierError, proven) can answer inside pi. The CLI owns its
 * auth (laptop login) and its own agentic loop; this spike answers one
 * question: does text come back through pi's provider contract?
 *
 * Known spike limits (verdict input, not bugs to fix here):
 * - blocking: whole reply pushed as one text delta (no true streaming)
 * - tools requested by pi are answered text-only (CLI runs its own loop)
 * - one-shot sessions: no multi-turn CLI session reuse (--continue)
 */
import { spawn } from "node:child_process";
import type {
	Api,
	AssistantMessage,
	AssistantMessageEventStream,
	Context,
	Model,
	SimpleStreamOptions,
} from "@earendil-works/pi-ai";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const PROVIDER_ID = "zen-cli";
const DEFAULT_CLI_TIMEOUT_MS = 180000;

function flattenPrompt(context: Context): string {
	// The CLI model may prefer tool calls over text; pi's provider
	// contract needs text. This instruction is load-bearing (measured:
	// bare prompts get `date` executions, instructed ones answer).
	// ZEN_CLI_ALLOW_TOOLS=1 drops it for action runs where the CLI's
	// own tools should do the work (pi cannot issue tool calls through
	// this text-only provider — measured contract limit, see M3).
	const parts: string[] =
		process.env.ZEN_CLI_ALLOW_TOOLS === "1"
			? []
			: [
					"Answer in plain text only. Do not run any commands, tools, or shell invocations; the caller cannot execute them.",
				];
	if (context.systemPrompt) parts.push(`[system]\n${context.systemPrompt}`);
	for (const m of context.messages) {
		if (m.role === "user") {
			const text = typeof m.content === "string" ? m.content : m.content.map((c: any) => c.text ?? "").join("\n");
			if (text.trim()) parts.push(`[user]\n${text}`);
		} else if (m.role === "assistant") {
			const text = (m.content as any[]).map((b: any) => b.text ?? "").join("\n");
			if (text.trim()) parts.push(`[assistant]\n${text}`);
		} else if (m.role === "toolResult") {
			parts.push(`[tool result omitted in spike]`);
		}
	}
	return parts.join("\n\n");
}

export function runCli(cliModel: string, prompt: string, signal?: AbortSignal): Promise<string> {
	return new Promise((resolve, reject) => {
		const t0 = Date.now();
		const bin = process.env.OPENCODE_BIN ?? "opencode";
		const timeoutMs = Number(process.env.ZEN_CLI_TIMEOUT_MS ?? DEFAULT_CLI_TIMEOUT_MS);
		const child = spawn(bin, ["run", "--pure", "-m", cliModel, prompt], {
			timeout: timeoutMs,
			stdio: ["ignore", "pipe", "pipe"],
			env: { ...process.env },
		});
		let out = "";
		let err = "";
		const kill = () => child.kill("SIGKILL");
		signal?.addEventListener("abort", kill, { once: true });
		child.stdout.on("data", (d) => (out += d.toString()));
		child.stderr.on("data", (d) => (err += d.toString()));
		child.on("error", (e) => {
			signal?.removeEventListener("abort", kill);
			reject(e);
		});
		child.on("close", (code, sig) => {
			signal?.removeEventListener("abort", kill);
			const ms = Date.now() - t0;
			if (code === 0 && out.trim()) resolve(out.trim());
			else
				reject(
					new Error(
						`opencode code=${code} signal=${sig} elapsed=${ms}ms piAborted=${signal?.aborted} HOME=${process.env.HOME ?? "?"}: ${err.slice(0, 300) || out.slice(0, 300)}`,
					),
				);
		});
	});
}

export function streamZenCli(
	model: Model<Api>,
	context: Context,
	options?: SimpleStreamOptions,
): AssistantMessageEventStream {
	const stream = createAssistantMessageEventStream();
	const output: AssistantMessage = {
		role: "assistant",
		content: [],
		api: model.api,
		provider: model.provider,
		model: model.id,
		usage: {
			input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "pending",
		timestamp: Date.now(),
	};
	(async () => {
		try {
			const toolsRequested = context.tools?.length ?? 0;
			const cliModel = (model as any).cliRef ?? `opencode/${model.id}`;
			const prompt =
				(toolsRequested > 0 ? `[note: ${toolsRequested} tools were requested but this spike answers text-only]\n\n` : "") +
				flattenPrompt(context);
			const text = await runCli(cliModel, prompt, options?.signal);
			output.content.push({ type: "text", text } as any);
			stream.push({ type: "start", partial: output });
			stream.push({ type: "text_start", contentIndex: 0, partial: output });
			stream.push({ type: "text_delta", contentIndex: 0, delta: text, partial: output });
			stream.push({ type: "text_end", contentIndex: 0, content: text, partial: output });
			output.stopReason = "stop";
			stream.push({ type: "done", reason: output.stopReason, message: output });
			stream.end();
		} catch (error) {
			output.stopReason = options?.signal?.aborted ? "aborted" : "error";
			output.errorMessage = error instanceof Error ? error.message : JSON.stringify(error);
			stream.push({ type: "error", reason: output.stopReason, error: output });
			stream.end();
		}
	})();
	return stream;
}

const FREE_MODELS = [
	"big-pickle",
	"ling-3.0-flash-fin-free",
	"mimo-v2.5-free",
	"muse-spark-1.2-contributor-free",
	"muse-spark-1.3-contributor-free",
	"nemotron-3-ultra-free",
	"nemotron-3.5-lightning-free",
];

export default function (pi: ExtensionAPI) {
	pi.registerProvider(PROVIDER_ID, {
		baseUrl: "cli://opencode",
		apiKey: "cli-login",
		api: "zen-cli-api",
		models: FREE_MODELS.map((id) => ({
			id,
			name: `${id} (via opencode CLI)`,
			input: ["text"],
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
			contextWindow: 128000,
			maxTokens: 4096,
			cliRef: `opencode/${id}`,
		})),
		streamSimple: streamZenCli,
	} as any);
}
