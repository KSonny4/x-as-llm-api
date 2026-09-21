# Reviewed Coding Index identity mappings

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

Explicitly **unmatched**: MiMo-V2.5 free (AA slug names 0424; exact dated
version not established), Nemotron Ultra reasoning variants without verified
setting equivalence, Big Pickle, and other unknowns. No generic suffix
stripping, slash removal, family matching or Intelligence Index fallback.

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
rule. North Mini Code/Laguna/etc. remain unmatched until their exact AA variants
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
