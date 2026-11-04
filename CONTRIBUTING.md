# Contributing

Contributions are welcome — bug reports, fixes and small focused features.

## Ground rules

- **Standard library only.** utm-governor's promise is
  "clone and run". Pull requests that add a third-party
  dependency will not be merged.
- **No network code. Ever.** The tool's whole trust
  proposition is that it reads files and fetches nothing —
  no "just check this one redirect" feature, no telemetry,
  no update check. The test suite greps the source for
  network APIs and fails on purpose if one appears.
- **The tool invents no conventions.** A new governed
  check is admissible only as a rule a conventions file
  can state; a check that hard-codes a naming convention,
  a platform's policy, or the maintainer's taste as if it
  were a fact will not be merged. The five-parameter
  scheme fact and query-key case-sensitivity are the only
  built-in authorities, and they are documented as such.
- **Build refuses; it does not fix.** Silently rewriting
  a user's components (lowercasing a source, trimming a
  campaign) to make a build pass turns governance into
  drift with better PR. Violations are reported; the
  owner of the conventions decides.
- **Config-gated stays config-gated.** The five governed
  classes must never fire without a conventions file that
  states their rule, and no-config output must keep
  naming them as skipped.
- **Strict conventions validation stays strict.** An
  unknown key or an invalid regex failing loudly is a
  feature: a governance file with a typo must never
  silently govern nothing.
- **Duplicates stay informational.** One link registered
  twice can be deliberate; promoting `duplicate` to an
  error (or to exit 1 on its own) changes a stated
  product choice. The conflicting signature is the error
  signal in that family.
- **Both directions tested.** A behaviour change needs a
  test where good input succeeds and bad input fails
  cleanly — not just one side. The sample registry's
  counts are hand-derived in the test file's header; if
  you change the sample, re-derive them by hand, never
  copy the tool's own output into the expectations.

## Getting started

```bash
git clone https://github.com/jasveerai88/utm-governor
cd utm-governor
python3 -m unittest discover -s tests -v
python3 src/utm_governor.py lint examples/sample-registry.json --config examples/conventions.json
```

## Pull requests

1. Fork, branch, and keep the change to one topic.
2. Add or update tests under `tests/`; the full suite must pass.
3. Note the change in `CHANGELOG.md` under an "Unreleased" heading.
4. Describe the behaviour change with a real before/after run if
   the CLI output changes.
