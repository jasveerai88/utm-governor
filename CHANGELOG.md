# Changelog

## v0.1.0 — 2026-11-04

First release.

- **Govern campaign links before they pollute analytics —
  locally, offline.** The governance half of the link stack
  that UTM.io ($19–159/mo), CampaignTrackly, UTMTool and
  Terminus sell: a conventions file, a link registry, a
  lint, and a governed builder. The sibling tool link-rot
  audits already-published description links for rot;
  utm-governor prevents the drift at creation time. There
  is **no network code in the tool** — it never fetches a
  URL.
- **`lint REGISTRY [--config CONVENTIONS]`** — per-link
  findings with exact reasons, registry-wide findings, and
  counts by class and severity. Registry input is JSON (a
  list, or `{"links": [...]}`; URL strings or
  `{"url", "label"}` objects) or CSV (a `url` column, an
  optional `label`). Exit 0 = no error/warning findings,
  1 = findings, 2 = error.
- **The rules come from the user's file, never from the
  tool.** The conventions file states only what its owner
  holds: `case` (lower/upper/any), `require` (short
  parameter names), `allowed_sources`, `allowed_mediums`,
  `campaign_pattern`, `value_pattern`, `allowed_params`
  (non-UTM keys). The five classes those rules gate —
  `missing-param`, `not-allowed`, `extra-param`,
  `case-violation`, `pattern-violation` — never fire
  without a config, and the output names them as skipped.
- **What the tool knows on its own authority:** the UTM
  scheme defines five parameters and query keys are
  case-sensitive — hence `unknown-param` for
  `utm_campagin` and `UTM_Source` — plus the link's shape
  (`malformed`) and a repeated key's ambiguity
  (`repeated-param`, warning). Everything else is
  arithmetic over the registry itself.
- **Registry-wide findings** — `case-drift` (the same
  value spelled two ways across the registry: analytics
  treats each spelling as a different value),
  `conflicting-duplicate` (one full
  source+medium+campaign signature pointing at two or
  more destinations) and `duplicate` (the identical link
  registered twice — informational only; it never sets
  exit 1 on its own).
- **Strict conventions validation** — an unknown key, a
  bad `case` value, an unknown `require` name, a wrong
  type or an invalid regex is a clean exit-2 error: a
  typo in a governance file must fail loudly, not
  silently govern nothing.
- **`build` and `build-batch`** — assemble links in the
  canonical parameter order (source, medium, campaign,
  term, content), percent-encoded, keeping the base's
  existing non-UTM query. Components are validated
  against the conventions file first and a violating link
  is **refused** (exit 2, violations named) — never
  silently rewritten. A base already carrying `utm_*`
  parameters is refused. In a batch, a refused row never
  sinks the good rows; the exit code says rows were
  refused.
- **Honesty rules, enforced in wording everywhere** — a
  clean lint means "consistent with the rules given",
  never "the links load"; allow-list membership is
  compared case-insensitively and the finding text says
  so, so a capitalisation reports once, as the case
  violation it is.
- **`--json` on every command** — one JSON object with
  the same facts and exit codes as the text view; errors
  are `{"error": ...}` objects, argparse usage errors
  included; build refusals additionally carry the
  structured `violations` list.
- **`SKILL.md`** at the repo root for AI coding agents:
  commands, the JSON schemas, exit codes, and the honesty
  rules (your rules not the tool's; no config, no governed
  verdict; build refuses, never fixes).
- Bundled examples: a fictional conventions file, a
  sample registry (nine fictional links, exactly one
  planted fault per class — 9 findings, 8 errors + 1
  info, hand-checkable), a clean CSV registry, and a
  batch CSV with one refused row.
- 49 stdlib-unittest tests: the sample's hand-counted
  numbers with and without a conventions file, every
  class in both directions, the conventions validation
  errors, the build refusals, the batch fixture, every
  input error exiting 2 cleanly with no traceback, the
  JSON summary recounted against the JSON findings, and
  a guard test that fails if network code ever enters
  the source.
- Pure Python standard library; local only; MIT licence.
