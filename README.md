# utm-governor

**Campaign links drift. Analytics pays for it.**

Every team that runs campaigns has the same quiet mess:
`utm_source=YouTube` in one link and `youtube` in the next,
so one source becomes two rows in every report; a
`utm_campagin` typo that attributes nothing; the same
campaign signature pointing at two different pages, merged
into one campaign forever; tiktok links in a registry whose
conventions never allowed tiktok. Paid tools sell the fix —
UTM.io at $19–159/mo, CampaignTrackly at $15/mo, UTMTool,
Terminus — and the paid half is never the builder (builders
are free everywhere). The paid half is *governance*: a
conventions file, a registry, and a lint that catches the
drift before it pollutes analytics.

`utm-governor` is that governance half, locally and free:
lint an existing link registry against **your own**
conventions file, and bulk-build new links that obey it.
It is the prevention half of the link stack — the sibling
tool [`link-rot`](https://github.com/jasveerai88/link-rot)
audits links already published in video descriptions for
rot; utm-governor governs how campaign links are made.

- Pure Python 3 standard library — no dependencies, no install step
- Local only — **there is no network code in this tool at
  all.** It never fetches a URL; it reads text.
- The honesty rule: **the conventions come from your file,
  never from this tool.** It invents no naming convention
  and enforces no platform policy — see below.
- Script-friendly exit codes: `0` = clean / everything
  built, `1` = findings or refused rows, `2` = error

## What it flags

Per link:

| Class | Severity | Meaning |
|---|---|---|
| `malformed` | error | no scheme, a non-web scheme, no host, a space in the URL |
| `unknown-param` | error | a `utm_*` key that is not one of the five the UTM scheme defines (`utm_campagin`), or a key case-mangled (`UTM_Source`) — query keys are case-sensitive, so analytics will not read it as intended |
| `missing-param` | error | a parameter your conventions file requires is absent — or present but empty. *Config-gated* |
| `not-allowed` | error | a source/medium outside your conventions file's allowed lists (membership compared case-insensitively; case itself is the case rule's job). *Config-gated* |
| `extra-param` | error | a non-UTM query key your conventions file's `allowed_params` does not permit. *Config-gated* |
| `case-violation` | error | a value not written in the case your conventions file requires. *Config-gated* |
| `pattern-violation` | error | a campaign/value that does not match your conventions file's regex. *Config-gated* |
| `repeated-param` | warning | the same query key twice in one link — different parsers keep different occurrences, so which value analytics records is ambiguous |

Across the whole registry (no single link can show these):

| Class | Severity | Meaning |
|---|---|---|
| `case-drift` | error | the same value spelled two ways across the registry (`youtube` ×2, `YouTube` ×1) — analytics treats each spelling as a different value |
| `conflicting-duplicate` | error | one full campaign signature (source+medium+campaign) pointing at two or more different destinations — analytics merges them |
| `duplicate` | info | the identical link registered more than once — fine if deliberate; listed, but it does **not** set exit 1 on its own |

**Config-gated means exactly that:** without `--config`,
those five classes never fire, and the output names them as
skipped. What runs without a conventions file is what needs
no one's rules: the link's shape, the five-parameter scheme
fact, and the registry's consistency with itself.

## The conventions file

JSON, every key optional — state only the rules you
actually hold:

```json
{
  "case": "lower",
  "require": ["source", "medium", "campaign"],
  "allowed_sources": ["youtube", "instagram", "newsletter", "partner-blog"],
  "allowed_mediums": ["social", "email", "cpc", "referral"],
  "campaign_pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
  "value_pattern": "^[A-Za-z0-9.-]+$",
  "allowed_params": ["ref"]
}
```

`case` is `"lower"`, `"upper"` or `"any"`. `require` names
parameters by short name (`source` … `content`).
`allowed_params` governs the *non*-UTM keys a link may
carry; the `utm_*` namespace is the scheme check's
territory. The file is validated strictly — an unknown key,
a bad regex, an unknown `require` name is a clean exit-2
error, because a typo in a governance file must fail
loudly, not silently govern nothing.

## The registry

JSON — a list of links, or `{"links": [...]}`; each link a
URL string or a `{"url": ..., "label": ...}` object. Or
CSV — a header row with a `url` column and an optional
`label` column. Malformed input of either kind is a clean
exit-2 error naming the entry — never a traceback.

## Usage

```bash
# 1. Lint the registry against your conventions
python3 src/utm_governor.py lint examples/sample-registry.json --config examples/conventions.json

# 2. Build one link (validated first; a violation is refused, never silently fixed)
python3 src/utm_governor.py build --base https://focusbrilliant.example/shop \
    --source youtube --medium social --campaign winter-sale-2026 \
    --config examples/conventions.json

# 3. Bulk-build from a CSV of components
python3 src/utm_governor.py build-batch examples/batch.csv --config examples/conventions.json
```

Every command takes `--json`: one JSON object with the
same facts and exit codes as the text view; errors are
`{"error": ...}` objects, argparse usage errors included.

### A real lint run (verbatim)

```text
$ python3 src/utm_governor.py lint examples/sample-registry.json --config examples/conventions.json
utm-governor v0.1.0 — lint · registry sample-registry.json
9 link(s) · 8 unique
This tool reads text and never fetches a link.
Conventions (conventions.json) — the rules came from this file:
  case: values must be lower
  require: utm_source, utm_medium, utm_campaign
  allowed_sources: youtube, instagram, newsletter, partner-blog
  allowed_mediums: social, email, cpc, referral
  campaign_pattern: ^[a-z0-9]+(-[a-z0-9]+)*$
  value_pattern: ^[A-Za-z0-9.-]+$
  allowed_params: ref

Findings by class:
  unknown-param: 1
  missing-param: 1
  not-allowed: 1
  case-violation: 1
  pattern-violation: 2
  case-drift: 1
  conflicting-duplicate: 1
  duplicate: 1 (informational)
Errors: 8 · warnings: 0 · info: 1

Per link:
  [winter-sale-video] https://focusbrilliant.example/shop?utm_source=youtube&utm_medium=social&utm_campaign=winter-sale-2026
    no findings
  [winter-sale-shorts] https://focusbrilliant.example/shop?utm_source=YouTube&utm_medium=social&utm_campaign=winter-sale-2026
    ! case-violation — utm_source value 'YouTube' is not lowercase — the conventions file's case rule requires 'youtube'
  [launch-email] https://focusbrilliant.example/launch?utm_source=newsletter&utm_medium=email
    ! missing-param — utm_campaign is required by the conventions file but has no value
  [typo-param] https://focusbrilliant.example/launch?utm_source=newsletter&utm_medium=email&utm_campaign=launch-2026&utm_campagin=launch-2026
    ! unknown-param — parameter 'utm_campagin' is not one of the five the UTM scheme defines (utm_source, utm_medium, utm_campaign, utm_term, utm_content) — analytics will not read it as a campaign parameter
  [off-list-source] https://focusbrilliant.example/shop?utm_source=tiktok&utm_medium=social&utm_campaign=winter-sale-2026
    ! not-allowed — utm_source value 'tiktok' is not in the conventions file's allowed_sources (youtube, instagram, newsletter, partner-blog) — membership was compared case-insensitively
  [underscored-campaign] https://focusbrilliant.example/shop?utm_source=instagram&utm_medium=social&utm_campaign=winter_sale
    ! pattern-violation — utm_campaign value 'winter_sale' does not match the conventions file's campaign_pattern ^[a-z0-9]+(-[a-z0-9]+)*$
    ! pattern-violation — utm_campaign value 'winter_sale' does not match the conventions file's value_pattern ^[A-Za-z0-9.-]+$
  [spring-promo-pricing] https://focusbrilliant.example/pricing?utm_source=partner-blog&utm_medium=referral&utm_campaign=spring-promo
    no findings
  [spring-promo-deals] https://focusbrilliant.example/deals?utm_source=partner-blog&utm_medium=referral&utm_campaign=spring-promo
    no findings
  [winter-sale-video-copy] https://focusbrilliant.example/shop?utm_source=youtube&utm_medium=social&utm_campaign=winter-sale-2026
    no findings

Across the registry:
  ! case-drift — utm_source appears as 'YouTube' ×1, 'youtube' ×2 across the registry — analytics treats each spelling as a different value, so one source silently becomes several rows
  ! conflicting-duplicate — the same campaign signature (utm_source=partner-blog, utm_medium=referral, utm_campaign=spring-promo) points at 2 different destinations — analytics merges them into one campaign, so neither destination's results can be told apart
  ! duplicate — the identical link is registered 2 times (winter-sale-video, winter-sale-video-copy) — fine if deliberate; a registry usually wants one entry per link

Verdict: ACTION — the findings above are the worklist; fix them in the registry (or in the conventions file, if the file is what is wrong).
(exit code: 1)
```

The sample registry is fictional (a Kelowna web studio's
links) with exactly one planted fault per class — the
counts above are hand-checkable.

### Real build runs (verbatim)

```text
$ python3 src/utm_governor.py build --base https://focusbrilliant.example/shop --source youtube --medium social --campaign winter-sale-2026 --config examples/conventions.json
https://focusbrilliant.example/shop?utm_source=youtube&utm_medium=social&utm_campaign=winter-sale-2026
(exit code: 0)

$ python3 src/utm_governor.py build --base https://focusbrilliant.example/shop --source YouTube --medium social --campaign winter-sale-2026 --config examples/conventions.json
ERROR: the components violate the conventions file: utm_source value 'YouTube' is not lowercase — the conventions file's case rule requires 'youtube'
(exit code: 2)
```

The builder validates *before* it assembles and refuses a
violating link — it does not lowercase your input behind
your back. Governance that quietly rewrites is just drift
with better PR. Parameters are emitted in the canonical
order (source, medium, campaign, term, content) after any
query the base already carries; values are
percent-encoded; a base that already carries a `utm_*`
parameter is refused (the components supply those).

```text
$ python3 src/utm_governor.py build-batch examples/batch.csv --config examples/conventions.json
utm-governor v0.1.0 — build-batch · batch.csv
3 row(s) · 2 built · 1 refused

  [video-main] https://focusbrilliant.example/shop?utm_source=youtube&utm_medium=social&utm_campaign=winter-sale-2026
  [video-endcard] https://focusbrilliant.example/shop?utm_source=youtube&utm_medium=social&utm_campaign=winter-sale-2026&utm_content=end-card
  [bad-source] REFUSED — the components violate the conventions file: utm_source value 'tiktok' is not in the conventions file's allowed_sources (youtube, instagram, newsletter, partner-blog) — membership was compared case-insensitively
(exit code: 1)
```

A refused row never sinks the batch: the good rows still
build, the bad rows are named with their violations, and
the exit code says rows were refused.

### A clean run (verbatim, abridged)

```text
$ python3 src/utm_governor.py lint examples/clean-registry.csv --config examples/conventions.json
utm-governor v0.1.0 — lint · registry clean-registry.csv
3 link(s) · 3 unique
...
Findings: none
Errors: 0 · warnings: 0 · info: 0
...
Verdict: CLEAN — every link obeys the checks that ran. That says the registry is consistent with the rules given, never that the links load.
(exit code: 0)
```

## Honesty rules

- **Your rules, not the tool's.** Every governed finding
  names the conventions-file rule it came from. If the
  finding is wrong, the file is what to fix — the verdict
  line says so.
- **The one fact the tool owns:** the UTM scheme defines
  five parameters, and query keys are case-sensitive.
  Everything else it asserts is arithmetic over your files
  (two spellings in one registry, one signature on two
  destinations).
- **A clean lint is not "the links work".** It means the
  registry is consistent with the rules given. Liveness is
  a network question this tool deliberately never asks.
- **Allow-list membership is case-insensitive by design**,
  and the finding text says so — otherwise every
  capitalisation would double-report as both a case
  violation and a membership violation.

## Known limits

- Duplicate comparison is textual after light
  normalisation (scheme/host case, one trailing slash,
  fragment dropped). Two URLs with the same parameters in
  a different order are *not* reported as duplicates.
- When a parameter repeats in one link, convention checks
  judge the first occurrence; the repeat itself is the
  `repeated-param` warning.
- `build` always requires source, medium and campaign
  components — they are the attribution core; a conventions
  file can additionally require term/content.
- Percent-decoding is not applied to registry values
  before checks: a value written `winter%20sale` is
  checked as written.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

49 stdlib-unittest tests: the sample's hand-counted
numbers (with and without a conventions file), every class
in both directions, the conventions-file validation errors,
the build refusals, the batch fixture, every input error
exiting 2 cleanly with no traceback, the JSON summary
recounted against the JSON findings, and a guard test that
fails if network code ever enters the source.

## Licence

MIT — see `LICENSE`. If this tool saves you a UTM.io
invoice, consider sponsoring via the button on the repo.
