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

Explicitly **unmatched**: Muse Spark contributor routes (AA has distinct max and
xhigh scores; no proven configuration equivalence), MiMo-V2.5 free (AA slug names
0424; exact dated version not established), Nemotron Ultra reasoning variants
without verified setting equivalence, Big Pickle, and other unknowns. No generic
suffix stripping, slash removal, family matching or Intelligence Index fallback.

A new mapping requires source-named evidence and regression tests. Provider
namespaces stay distinct; one provider mapping does not authorize another.
