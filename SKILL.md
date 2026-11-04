---
name: utm-governor
description: Govern campaign (UTM) links locally — lint a link registry (JSON list / {"links": [...]} / CSV with a url column) against the USER'S OWN conventions file, and build new links that obey it. Lint classes: malformed (no/non-web scheme, no host, space), unknown-param (a utm_* key not among the five the UTM scheme defines — utm_source, utm_medium, utm_campaign, utm_term, utm_content — or a case-mangled key like UTM_Source; query keys are case-sensitive), missing-param / not-allowed / extra-param / case-violation / pattern-violation (ALL config-gated — they fire only when the conventions file states the rule; without --config they never fire and the output names them as skipped), repeated-param (same key twice in one link — warning), and registry-wide case-drift (same value, two spellings), conflicting-duplicate (one source+medium+campaign signature, 2+ destinations), duplicate (identical link registered twice — info only, never sets exit 1 alone). Conventions file is strict JSON: case (lower/upper/any), require (short names), allowed_sources, allowed_mediums, campaign_pattern, value_pattern (regexes), allowed_params (non-utm keys); unknown keys/bad regex/unknown require names are exit-2 errors. build assembles one link (canonical param order, percent-encoded, existing non-utm base query kept, base carrying utm_* refused) and REFUSES components that violate the conventions file — it never silently rewrites input; build-batch does one row per CSV row (base, source, medium, campaign, term, content, label), refused rows named, good rows still built. THE TOOL NEVER FETCHES ANYTHING — there is no network code in it; a clean lint means the registry is consistent with the rules given, NEVER that the links load. THE RULES COME FROM THE USER'S FILE, never from the tool — it invents no naming convention and enforces no platform policy. Exit 0 clean/all built, 1 = findings or refused rows, 2 = clean error ({"error": ...} under --json, argparse included; build refusals under --json also carry a "violations" list), never a traceback.
---

# utm-governor — agent skill

## Purpose

Campaign links drift in exactly the ways analytics cannot
forgive: `YouTube` vs `youtube` splits one source into two
report rows, a `utm_campagin` typo attributes nothing, one
campaign signature lands on two pages and is merged
forever, off-convention sources creep in. Paid tools
(UTM.io $19–159/mo, CampaignTrackly, UTMTool, Terminus)
sell the governance: a conventions file, a registry, a
lint, a governed builder. utm-governor does that job
locally on files the user already has. It is the
prevention half of the link stack; the sibling tool
link-rot audits already-published description links for
rot. Different job, same shelf.

**The honesty core of this tool:** the rules come from the
user's conventions file, never from the tool. It invents
no naming convention and enforces no platform's policy.
On its own authority it knows one fact — the UTM scheme
defines five parameters and query keys are case-sensitive
— plus arithmetic over the registry itself (two spellings
of one value, one signature on two destinations). And it
never fetches a URL: there is no network code in the
source (a test pins that).

## When to use / not use

Use when:
- A registry of campaign links exists (spreadsheet export,
  JSON list, CSV with a `url` column) and its owner has —
  or will write — a conventions file: allowed sources and
  mediums, a case rule, a campaign pattern.
- A pipeline generates campaign links: build them with
  `build` / `build-batch` under `--config` so a violating
  link cannot be produced in the first place.
- You need the registry-wide facts before a reporting
  period: case-drift and conflicting signatures are the
  two that silently corrupt a quarter's numbers.

Do NOT use when:
- You need liveness or click data. This tool cannot tell
  you a link loads or converts; it reads text.
- There is no conventions file and the user will not
  write one. The no-config lint still runs (shape, scheme
  fact, registry consistency), but do not present its
  silence on governed classes as approval — the output
  lists them as skipped because they need the user's
  rules.
- The links live only inside prose (video descriptions,
  documents). That is link-rot's input shape, not a
  registry.

## Commands

```bash
# Lint a registry (JSON or CSV) against a conventions file
python3 src/utm_governor.py lint REGISTRY.json --config CONVENTIONS.json [--json]
python3 src/utm_governor.py lint REGISTRY.csv [--config CONVENTIONS.json] [--json]

# Build one governed link
python3 src/utm_governor.py build --base URL --source S --medium M \
    --campaign C [--term T] [--content X] [--config CONVENTIONS.json] [--json]

# Bulk-build: one link per CSV row
python3 src/utm_governor.py build-batch BATCH.csv [--config CONVENTIONS.json] [--json]
```

Inputs:
- Registry JSON: a list, or `{"links": [...]}`; entries
  are URL strings or `{"url", "label"|"name"|"id"}`
  objects. An entry's ref is its label, else its position
  (`links[2]`). CSV: header row, `url` column required
  (case-insensitive), `label` optional; ragged rows are an
  error naming the row.
- Conventions JSON (all keys optional; unknown keys are
  an error): `case` — `"lower" | "upper" | "any"`;
  `require` — short names among source, medium, campaign,
  term, content; `allowed_sources` / `allowed_mediums` —
  string lists, membership compared case-insensitively;
  `campaign_pattern` / `value_pattern` — regexes (matched
  with `re.search`, so anchors are the file author's
  choice); `allowed_params` — non-utm query keys a link
  may carry.
- Batch CSV: header must carry `base`, `source`,
  `medium`, `campaign`; `term`, `content`, `label`
  optional. Blank cells are absent components.

## Checks (exact)

Per link, from the link as written:
- `malformed` (error): whitespace anywhere; scheme
  missing or not http/https; no host; unparseable. A
  malformed link gets no further checks — its shape is
  the finding.
- `unknown-param` (error): a query key that is not
  exactly one of the five, where the key case-matches one
  of the five (`UTM_Source`) or its casefold starts with
  `utm_` (`utm_campagin`). All other keys are not this
  check's business.
- `extra-param` (error, config-gated on
  `allowed_params`): a non-utm-namespace key not in the
  list. The utm_* namespace never fires this class.
- `repeated-param` (warning): any query key appearing 2+
  times. Convention checks then judge the FIRST
  occurrence.
- Config-gated, over the parsed values (via
  `check_components`, shared with build):
  `missing-param` — a `require`d parameter absent or
  present-but-empty; `not-allowed` — source/medium not in
  the allowed list (case-insensitive membership);
  `case-violation` — a value unequal to its lower/upper
  form under the `case` rule (`"any"` disables);
  `pattern-violation` — campaign failing
  `campaign_pattern`, or any value failing
  `value_pattern` (one finding per failed pattern per
  value).

Registry-wide (over parseable links):
- `case-drift` (error): per parameter, values grouped by
  casefold; a group with 2+ distinct spellings yields one
  finding naming each spelling with its count and the
  entries carrying the value.
- `conflicting-duplicate` (error): links whose FULL
  signature — source, medium, campaign all present
  (term/content as written) — maps to 2+ distinct bases.
  A base is the normalised destination with utm_*
  parameters removed (scheme/host lowercased, one
  trailing slash stripped, non-utm query kept in order).
  A partial signature never conflicts.
- `duplicate` (info): one normalised full URL (same
  normalisation, query verbatim — parameter ORDER
  matters) registered 2+ times.

Build: the base must be an absolute http(s) URL with a
host and no utm_* parameter of its own (refused, exit 2).
Existing non-utm query pairs are kept, first. Components
are validated with the same `check_components`; any
violation refuses the build (exit 2, violations listed) —
input is never silently rewritten (no auto-lowercasing).
Output parameters follow the canonical order source,
medium, campaign, term, content; values are
percent-encoded (`urlencode` with `quote_via=quote`, so
spaces are `%20`); the base's fragment is dropped.

## Output JSON schema (`--json`)

Common: `tool` (`"utm-governor"`), `version`, `command`,
`scope` (the your-rules / never-fetched statement).

`lint` adds `registry_file`, `conventions_file` (name or
null), `conventions` (the active rules as text lines),
`checks_skipped` (the five config-gated class names when
no config was given, else `[]`), `entries` — each `{ref,
url, findings}` where a finding is `{class, severity,
reason}` — `registry_findings` — each `{class, severity,
reason}` plus, by class: `parameter`/`spellings`/
`entries` (case-drift), `signature`/`targets`
(conflicting-duplicate; targets are `{base, entries}`),
`url`/`entries` (duplicate) — and `summary`:
`{entries, unique_links, findings_by_class, errors,
warnings, infos, entries_without_findings}`.
`findings_by_class` counts FINDINGS (per-link +
registry-wide), only non-zero classes, in class order.

`build` adds `conventions_file`, `url`, and `params`
(the full `utm_*` keys actually used). On refusal the
error object is `{"error": ..., "violations": [{class,
severity, reason}]}` with exit 2.

`build-batch` adds `batch_file`, `conventions_file`,
`built` (`[{ref, url}]`), `refused` (`[{ref,
violations}]` — a row whose base is unusable carries one
`invalid-row` violation), and `summary` `{rows, built,
refused}`.

On any other error, stdout is a single object:
`{"error": "<message>"}` with exit code 2 — including
argparse usage errors in `--json` mode. Never plain text,
never a traceback.

## Exit codes

- `0` — lint: no error or warning findings (plain
  duplicates may still be listed; they are notes).
  build: the link was produced. build-batch: every row
  built.
- `1` — lint: error or warning findings exist; the
  findings ARE the deliverable — quote them, don't
  summarise them away. build-batch: at least one row was
  refused (the built rows are still output).
- `2` — ERROR: registry/conventions/batch file missing,
  unreadable, invalid, or the wrong shape; a conventions
  file with an unknown key, bad case value, unknown
  require name or invalid regex; a build base that is not
  an absolute web URL or already carries utm_*; build
  components that violate the conventions file; an
  invalid flag. No lint facts may be quoted from a failed
  run.

## Limits & honesty rules the agent must respect

- **Your rules, not the tool's.** Never present a
  governed finding as a universal rule or a platform
  policy — it is the user's conventions file speaking.
  If a finding looks wrong, the fix may be the file;
  the verdict line says exactly that.
- **No config, no governed verdict.** Without `--config`,
  five classes are skipped and named as skipped. Do not
  report a no-config lint as "the registry follows our
  conventions" — no conventions were supplied.
- **Structural, never live.** A clean lint means the
  registry is consistent with the rules given — never
  that the links load, and never that they convert.
- **Membership is case-insensitive; case is separate.**
  `YouTube` passes an `allowed_sources: ["youtube"]`
  check and fails a `case: "lower"` check. Report the
  class that actually fired.
- **Build refuses; it does not fix.** Do not lowercase,
  trim or otherwise edit components yourself to make a
  refused build pass and then present the result as
  governed — surface the violation and let the owner of
  the conventions decide.
- **Exit 2 means nothing was checked.** Do not
  reconstruct findings by reading the files yourself and
  presenting them as the tool's — fix the input and
  re-run.
- Local only: the tool reads only the files named on the
  command line and sends nothing anywhere.
