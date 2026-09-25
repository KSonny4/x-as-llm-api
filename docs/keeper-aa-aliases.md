# Coding Index model matching (Keeper ↔ Artificial Analysis)

## Current policy — owner-authorized AI matching, 2026-09-25

The owner explicitly authorized AI-assisted name matching on 2026-09-25
("please use AI for name matching if it helps"). This **supersedes** the
2026-09-20 "exact slugs only / no suffix stripping / no fuzzy joins" rule
recorded below; the reviewed alias tables below remain in force and win over
everything else. Implementation: `keeper/aa_match.py` (+ `keeper/aa.py`).

Precedence per `(provider, model)`:

1. **alias** — reviewed `aa.ALIASES` entry, taken verbatim (confidence 1.0).
2. **exact** — the Keeper model id is an AA slug.
3. **normalized** — lowercase; drop everything up to the last `/` (provider,
   vendor and `stealth/` namespaces); drop a trailing `:free`, `-free`,
   `_free`, ` free` or `(free)`; every other separator (dots, underscores,
   spaces) becomes `-`; the result must equal an AA slug exactly.
4. **ai** — for *served* models (`working_keys > 0`) still unresolved, at
   the daily AA refresh only (own daemon thread, never on the request path,
   at most 10 LLM calls per refresh). Keeper sends the id plus a shortlist of
   up to 8 AA entries (slug, name, creator, coding index) that share a name
   token, ranked by string/token similarity with a creator/vendor bonus, to
   `keeper-coder` in-process (`service_api.chat`, consumer
   `keeper-aa-matcher`, plain text — no `response_format`, so free
   genuine-CLI routes stay eligible and the paid fallback is last resort).
   A decision `{slug|null, confidence, reason}` is **accepted only if**
   confidence ≥ 0.8, the slug is in the shortlist, and every version number
   in the id also appears in the chosen entry's slug/name. Rejections are
   stored with `rejected: low_confidence | out_of_shortlist |
   version_mismatch | no_candidate` (no LLM call when nothing shares a name
   token, e.g. `big-pickle`, `space-bunny`).

Matching is separate from scoring: an exact/normalized hit ends resolution
even when AA has no Coding Index for that slug yet (the model stays unscored
and is never sent to the LLM). Unless the Keeper id itself ends in an effort
label (`-max|-xhigh|-high|-medium|-low|-minimal|-reasoning|-non-reasoning`),
a normalized or AI match takes the **lowest scored member of its AA family** (same
creator + name without the trailing parenthesised label, e.g. "Qwen3.8 27B
(xhigh|medium|low|Non-reasoning)"), extending the muse-spark precedent below
so ranking never over-promises. Aliases and exact slug matches are not
lowered: an exact slug already names the precise AA variant.

Secondary key (owner request 2026-09-25): models AA lists without a Coding
Index (e.g. GPT-6 Luna, released 2026-09-22, Intelligence Index 37.3 only)
are ordered by the AA **Intelligence Index** after every Coding-scored model
and before fully unscored ones. It is exposed as `intelligence_index` and is
never reported as, or substituted for, a Coding Index.

Persistence/audit: AI decisions live in `aa-matches.json` next to the AA
cache (`$(dirname AA_CACHE)`, prod `/var/lib/keeper/aa-matches.json`) with
`slug, method, confidence, reason, decided_at, candidates, shortlist_hash`
plus a `served` snapshot of every served model's slug/method/score. A model
is re-asked only when it has no decision or its shortlist (set of candidate
slugs) changed; decisions whose slug disappeared from AA are dropped. LLM
failure keeps prior decisions and leaves new models unscored. The AA cache now
also stores the public slug index (`slug → name, creator, coding`); a cache
without it is refetched once at startup. `KEEPER_AA_AI_MATCH=0` disables the
AI step.

Provenance: `/api/v2/catalog` rows carry `coding_index_match`
(`{slug, method, confidence[, picked, reason, decided_at]}` or `null`;
`picked` is the matched slug when the family minimum replaced it), and the
`aa` block carries `match_decided_at` / `match_error`.

### Why GPT-6 Luna was unscored (diagnosed 2026-09-25)

Not a matching problem. Keeper's `openai / gpt-6-luna` already equals AA slug
`gpt-6-luna` ("GPT-6 Luna (max)", creator `openai`, released 2026-09-22).
AA lists it — and its xhigh/high/medium/low/non-reasoning variants — with
`evaluations.artificial_analysis_coding_index = null` (only the Intelligence
Index, 37.3, is published). `parse_scores` keeps Coding Index only, so the
slug never entered the score table. Luna now shows `coding_index_match =
{slug: gpt-6-luna, method: exact}` with `coding_index: null`, and will score
(family minimum) as soon as AA publishes its Coding Index. It must not be
matched to `gpt-5-6-luna` (a different version); the Intelligence Index is
still never used as a fallback.

### Served models on 2026-09-25 (live AA snapshot + live catalog)

| Provider / model | AA slug | Method | Coding Index |
|---|---|---|---|
| opencode-zen / muse-spark-1.3-contributor-free | muse-spark-1-3 | alias | 75.8 |
| opencode-zen / ling-3.0-flash-fin-free | ling-3-0-flash-fin | alias | 55.6 |
| opencode-zen / nemotron-3-ultra-free | nvidia-nemotron-3-ultra-550b-a55b | ai (0.9, live keeper-coder trial) | 49.3 |
| opencode-zen / nemotron-3.5-lightning-free | nemotron-3-5-lightning | alias | 26.8 |
| openai / gpt-6-luna | gpt-6-luna | exact | — (AA Coding Index null) |
| opencode-zen / mimo-v2.6-flash-free | — | ai: null (AA has V2.6-Pro and V2-Flash only) | — |
| opencode-zen / big-pickle | — | no_candidate | — |
| opencode-zen / space-bunny-free | — | no_candidate | — |
| openrouter / stealth/space-bunny-alpha | — | no_candidate | — |

`nemotron-3-ultra-free` was left unmatched on 2026-09-20 for lack of verified
reasoning-setting equivalence; AA lists a single (Reasoning) entry, and the
AI step now accepts it under the thresholds above. Deterministic matching
alone raises catalog-wide scored rows from 43 to 295 of 1183; the family
minimum lowers six previously exact-matched unserved rows (e.g.
`opencode-zen/claude-opus-5` 78.0 → 66.9, `gpt-6-astra` 76.9 → 75.7).

---

## History: reviewed alias tables (2026-09-20/21, still in force)

Reviewed 2026-09-20 against two primary sources:

1. [OpenCode Zen official endpoint/pricing tables](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/zen.mdx)
2. [Artificial Analysis model data API](https://artificialanalysis.ai/api/v2/data/llms/models)
   (parent's authenticated metadata retrieval at 2026-09-20T20:00:07Z; no API key
   or secret-bearing response is retained here).

| Provider + exact route ID | Official Zen display name | Exact AA name | AA slug |
|---|---|---|---|
| opencode-zen / ling-3.0-flash-fin-free | Ling 3.0 Flash Fin Free | Ling-3.0-flash-Fin | ling-3-0-flash-fin |
| opencode-zen / nemotron-3.5-lightning-free | Nemotron 3.5 Lightning Free | Nemotron 3.5 Lightning | nemotron-3-5-lightning |

The display names identify the same explicitly named/versioned variants; Free is
the provider's documented endpoint tier, not an inferred model family. No AA
reasoning-effort or dated-version distinction is present in these two names.
Both direct and genuine-CLI transports use this provider/model identity, but
retain independent availability evidence. Code contains **no scores** in the
alias table: the daily cached Coding Index remains the score source.

Explicitly **unmatched** (2026-09-20): MiMo-V2.5 free (AA slug names 0424; exact dated
version not established), Nemotron Ultra reasoning variants without verified
setting equivalence, Big Pickle, and other unknowns. No generic suffix
stripping, slash removal, family matching or Intelligence Index fallback.
*(Superseded 2026-09-25 by the policy above, except: still no Intelligence
Index fallback, and MiMo-V2.5 still does not normalize to the dated slug.)*

Mapped 2026-09-21 with live AA verification: `muse-spark-1.3-contributor-free`
→ slug `muse-spark-1-3` (Muse Spark 1.3 max, Coding Index 75.8). AA also lists
`muse-spark-1-3-xhigh` at 76.5; the free contributor endpoint carries no effort
label, so the mapping takes the lower score and never over-promises. Either
variant tops current free ranking, so the choice does not affect selection
order today.

A new mapping requires source-named evidence and regression tests. Provider
namespaces stay distinct; one provider mapping does not authorize another.

Additional provider-scoped spellings reviewed against the primary
[OpenRouter catalog](https://openrouter.ai/api/v1/models) and
[Kilo catalog](https://api.kilo.ai/api/gateway/models), retrieved 2026-09-20:

| Provider(s) | Exact ID | Catalog display name | AA slug |
|---|---|---|---|
| openrouter, kilocode | inclusionai/ling-3.0-flash-fin:free | inclusionAI: Ling 3.0 Flash Fin (free) | ling-3-0-flash-fin |
| openrouter, kilocode | nvidia/nemotron-3.5-lightning:free | NVIDIA: Nemotron 3.5 Lightning (free) | nemotron-3-5-lightning |

Each is an individually reviewed entry, not a provider-prefix or `:free` stripping
rule (superseded 2026-09-25: normalization now performs that stripping for
every provider). North Mini Code/Laguna/etc. remain unmatched until their exact AA variants
are verified. These joins do not establish availability or pricing eligibility.

Further exact unqualified names were cross-checked against the same primary
catalogs and the complete parent-retrieved AA name/slug snapshot on 2026-09-20:

| Provider(s) | Exact ID | Catalog name → exact AA name | AA slug |
|---|---|---|---|
| openrouter, kilocode | inclusionai/ling-3.0-flash-vl:free | inclusionAI: Ling 3.0 Flash VL (free) → Ling-3.0-flash-VL | ling-3-0-flash-vl |
| openrouter, kilocode | thinkingmachines/inkling-small:free | Thinking Machines: Inkling Small (free) → Inkling Small | inkling-small |
| openrouter, kilocode | cohere/north-mini-code:free | Cohere: North Mini Code (free) → North Mini Code | north-mini-code |
| openrouter, kilocode | liquid/lfm-2.5-2.6b:free | LiquidAI: LFM2.5-2.6B (free) → LFM2.5-2.6B | lfm2-5-2-6b |
| kilocode | stepfun/step-3.7-flash:free | StepFun: Step 3.7 Flash (free) → Step 3.7 Flash | step-3-7-flash |

This establishes the North Mini Code name equivalence previously left pending
above. Qwen 3.8 27B (xhigh/medium/low/non-reasoning), GLM 5.2
(max/non-reasoning), and non-small Inkling (xhigh) remain unmatched because the
endpoint's corresponding reasoning configuration is not established.
*(2026-09-25: these now normalize and take the family minimum — Qwen3.8 27B
44.6 (Non-reasoning), GLM-5.2 46.5 (Non-reasoning), Inkling 52.1.)*
