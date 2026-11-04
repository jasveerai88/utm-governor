#!/usr/bin/env python3
"""utm-governor — govern campaign links before they pollute
analytics: lint a local link registry against YOUR OWN
conventions file, and bulk-build new links that obey it.

Paid tools (UTM.io at $19–159/mo, CampaignTrackly, UTMTool,
Terminus) sell the governance half of the link stack: the
conventions, the registry, the checking. The builder half is
free everywhere; the lint is the paid half. This tool does
both halves locally, on files you already have, for free:

  lint REGISTRY [--config CONVENTIONS] [--json]
            every link in the registry checked for shape
            facts and — when a conventions file is given —
            against the rules in it: required parameters,
            allowed sources/mediums, value case, campaign
            and value patterns, allowed extra parameters.
            Plus the registry-wide facts no single link can
            show: case-drift (the same value spelled two
            ways across the registry), conflicting duplicates
            (one UTM signature, two destinations) and plain
            duplicates.
  build --base URL --source S --medium M --campaign C
        [--term T] [--content X] [--config CONVENTIONS]
        [--json]
            assemble one link from its components, in the
            canonical parameter order, percent-encoded. With
            a conventions file the components are validated
            first and a violating link is REFUSED, never
            silently fixed — governance that quietly rewrites
            your input is just drift with better PR.
  build-batch BATCH.csv [--config CONVENTIONS] [--json]
            the bulk builder: one row per link (base, source,
            medium, campaign, term, content), each row built
            or refused with its violations named.

The honesty core: THE RULES COME FROM YOUR FILE, NOT FROM
THIS TOOL. utm-governor invents no naming convention and
enforces no platform's policy. It knows exactly one thing on
its own authority: the UTM scheme defines five parameters —
utm_source, utm_medium, utm_campaign, utm_term, utm_content
— and query keys are case-sensitive, so a key that is not
exactly one of those five (utm_campagin, UTM_Source) is a
parameter analytics will not read as intended. Everything
else a lint can flag — which sources are allowed, which case
values must be in, what a campaign name may look like — is
checked ONLY when your conventions file says so, and the
output says which checks were active and which were skipped.
Without --config, lint runs the structural and
registry-internal checks only. The tool never fetches a URL;
it reads text.

Registry input — JSON or CSV (chosen by file extension):
  JSON: a list of links, or {"links": [...]}. Each link is a
  URL string, or an object {"url": ..., "label"/"name"/"id":
  ...}. An entry is referred to by its label, else its
  position ("links[2]").
  CSV: a header row, then one link per row; a "url" column is
  required (matched case-insensitively), a "label" column is
  optional.

Conventions file — JSON object, every key optional:
  case              "lower" | "upper" | "any" — the case
                    every utm value must be written in.
  require           list of short names among "source",
                    "medium", "campaign", "term", "content"
                    that must be present (and non-empty).
  allowed_sources   list of permitted utm_source values
                    (membership is compared case-insensitively;
                    case itself is the case rule's job).
  allowed_mediums   same, for utm_medium.
  campaign_pattern  regex a utm_campaign value must match.
  value_pattern     regex every utm value must match.
  allowed_params    list of NON-utm query keys permitted in
                    a link (e.g. ["ref"]); when present, any
                    other non-utm key is a finding.
  Unknown keys, wrong types, a bad case value, an unknown
  require name or an invalid regex are a clean exit-2 error —
  a typo in a governance file must fail loudly, not silently
  govern nothing.

Exit codes: 0 = clean / everything built · 1 = findings that
need action (lint) or rows refused (build-batch); plain
duplicates never set it on their own · 2 = ERROR — clean
message, never a traceback; with --json the error is
{"error": ...}. Every command takes --json: one JSON object
with the same facts and exit codes as the text view.
"""
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, \
    urlunsplit

__version__ = "0.1.0"
TOOL = "utm-governor"

# The five parameters the UTM scheme defines, in canonical
# order. Short name -> full query key.
PARAMS = ["source", "medium", "campaign", "term", "content"]
KEY_OF = {name: f"utm_{name}" for name in PARAMS}
NAME_OF = {v: k for k, v in KEY_OF.items()}

SEVERITY = {
    "malformed": "error",
    "unknown-param": "error",
    "missing-param": "error",
    "not-allowed": "error",
    "extra-param": "error",
    "case-violation": "error",
    "pattern-violation": "error",
    "repeated-param": "warning",
    "case-drift": "error",
    "conflicting-duplicate": "error",
    "duplicate": "info",
}

CLASS_ORDER = [
    "malformed", "unknown-param", "missing-param",
    "not-allowed", "extra-param", "case-violation",
    "pattern-violation", "repeated-param", "case-drift",
    "conflicting-duplicate", "duplicate",
]

# Classes a conventions file gates. Without --config these
# never fire and the output names them as skipped.
CONFIG_CLASSES = ["missing-param", "not-allowed", "extra-param",
                  "case-violation", "pattern-violation"]

CONVENTION_KEYS = {
    "case", "require", "allowed_sources", "allowed_mediums",
    "campaign_pattern", "value_pattern", "allowed_params",
}

SCOPE_NOTE = ("rules come from your conventions file, never "
              "from this tool; without one, only structural "
              "and registry-internal checks run. No URL was "
              "fetched — this tool reads text")


class ToolError(Exception):
    """A clean, user-facing failure (printed as ERROR, exit 2).
    May carry structured detail (e.g. build violations) for
    the JSON error object."""

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# conventions
# ---------------------------------------------------------------------------

def load_conventions(path):
    """Read + strictly validate a conventions file -> a dict
    with compiled patterns. Raises ToolError on any problem:
    a governance file that is wrong must fail loudly."""
    name = Path(path).name
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ToolError(f"cannot read conventions file "
                        f"{path!r}: {exc}")
    except UnicodeDecodeError as exc:
        raise ToolError(f"conventions file {name!r} is not "
                        f"valid UTF-8 text: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"conventions file {name!r} is not "
                        f"valid JSON: {exc}")
    if not isinstance(data, dict):
        raise ToolError(f"conventions file {name!r}: top level "
                        f"must be a JSON object of rules")
    unknown = sorted(set(data) - CONVENTION_KEYS)
    if unknown:
        raise ToolError(
            f"conventions file {name!r}: unknown rule(s): "
            f"{', '.join(unknown)} (known: "
            f"{', '.join(sorted(CONVENTION_KEYS))}) — a typo "
            f"here would silently govern nothing")
    out = {}
    case = data.get("case")
    if case is not None:
        if case not in ("lower", "upper", "any"):
            raise ToolError(
                f"conventions file {name!r}: 'case' must be "
                f"\"lower\", \"upper\" or \"any\" (got {case!r})")
        out["case"] = case
    require = data.get("require")
    if require is not None:
        if not isinstance(require, list) or \
                not all(isinstance(r, str) for r in require):
            raise ToolError(
                f"conventions file {name!r}: 'require' must "
                f"be a list of parameter names")
        bad = [r for r in require if r not in PARAMS]
        if bad:
            raise ToolError(
                f"conventions file {name!r}: 'require' names "
                f"unknown parameter(s): {', '.join(bad)} "
                f"(the five are: {', '.join(PARAMS)})")
        out["require"] = list(dict.fromkeys(require))
    for field in ("allowed_sources", "allowed_mediums",
                  "allowed_params"):
        value = data.get(field)
        if value is not None:
            if not isinstance(value, list) or \
                    not all(isinstance(v, str) and v
                            for v in value):
                raise ToolError(
                    f"conventions file {name!r}: {field!r} "
                    f"must be a list of non-empty strings")
            out[field] = list(value)
    for field in ("campaign_pattern", "value_pattern"):
        value = data.get(field)
        if value is not None:
            if not isinstance(value, str):
                raise ToolError(
                    f"conventions file {name!r}: {field!r} "
                    f"must be a regex string")
            try:
                out[field] = re.compile(value)
            except re.error as exc:
                raise ToolError(
                    f"conventions file {name!r}: {field!r} "
                    f"is not a valid regex: {exc}")
            out[field + "_src"] = value
    return out


def describe_config(config):
    """The active conventions, as short human lines — the
    lint output states what governed it, never silently."""
    if config is None:
        return []
    lines = []
    if "case" in config:
        lines.append(f"case: values must be {config['case']}")
    if "require" in config:
        lines.append("require: " + ", ".join(
            KEY_OF[r] for r in config["require"]))
    if "allowed_sources" in config:
        lines.append("allowed_sources: " + ", ".join(
            config["allowed_sources"]))
    if "allowed_mediums" in config:
        lines.append("allowed_mediums: " + ", ".join(
            config["allowed_mediums"]))
    if "campaign_pattern" in config:
        lines.append("campaign_pattern: "
                     + config["campaign_pattern_src"])
    if "value_pattern" in config:
        lines.append("value_pattern: "
                     + config["value_pattern_src"])
    if "allowed_params" in config:
        lines.append("allowed_params: " + ", ".join(
            config["allowed_params"]))
    return lines


# ---------------------------------------------------------------------------
# registry loading
# ---------------------------------------------------------------------------

def _clean_entry(entry, index, origin):
    """One raw registry entry -> {ref, url}. Raises ToolError
    naming the entry on shape problems."""
    label = f"{origin}[{index}]"
    if isinstance(entry, str):
        if not entry.strip():
            raise ToolError(f"{label}: a link entry is an "
                            f"empty string")
        return {"ref": label, "url": entry}
    if not isinstance(entry, dict):
        raise ToolError(f"{label}: each link must be a URL "
                        f"string or an object with a 'url' "
                        f"(got {entry!r})")
    url = entry.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ToolError(f"{label}: a link object needs a "
                        f"non-empty 'url' string (got "
                        f"{entry!r})")
    ref = label
    for key in ("label", "name", "id"):
        value = entry.get(key)
        if value is not None and not isinstance(value, str):
            raise ToolError(f"{label}: field {key!r} must be "
                            f"a string (got {value!r})")
        if isinstance(value, str) and value.strip():
            ref = value.strip()
            break
    return {"ref": ref, "url": url}


def _load_json_registry(raw, name):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"registry file {name!r} is not valid "
                        f"JSON: {exc}")
    if isinstance(data, dict):
        if "links" not in data:
            raise ToolError(
                f"registry file {name!r}: a JSON object must "
                f"carry its links under a 'links' key")
        data = data["links"]
    if not isinstance(data, list):
        raise ToolError(
            f"registry file {name!r}: top level must be a "
            f"list of links or an object with a 'links' list "
            f"(got {type(data).__name__})")
    return [_clean_entry(e, i, "links") for i, e in
            enumerate(data)]


def _load_csv_registry(raw, name):
    try:
        rows = list(csv.reader(io.StringIO(raw), strict=True))
    except csv.Error as exc:
        raise ToolError(f"registry file {name!r} is not "
                        f"valid CSV: {exc}")
    if not rows:
        raise ToolError(f"registry file {name!r}: the CSV has "
                        f"no header row")
    header = [h.strip().lower() for h in rows[0]]
    if "url" not in header:
        raise ToolError(
            f"registry file {name!r}: the CSV needs a 'url' "
            f"column (header is: {', '.join(rows[0])})")
    entries = []
    for i, row in enumerate(rows[1:]):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise ToolError(
                f"registry file {name!r}: row {i + 2} has "
                f"{len(row)} field(s), the header has "
                f"{len(header)}")
        record = dict(zip(header, row))
        entries.append(_clean_entry(
            {"url": record["url"],
             "label": record.get("label")}, i, "row"))
    return entries


def load_registry(path):
    """Read a registry file (JSON or CSV by extension) -> a
    list of {ref, url}. Raises ToolError on any problem."""
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    if suffix not in (".json", ".csv"):
        raise ToolError(
            f"registry file {name!r}: utm-governor reads "
            f".json or .csv registries (got extension "
            f"{suffix!r})")
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ToolError(f"cannot read registry file "
                        f"{path!r}: {exc}")
    except UnicodeDecodeError as exc:
        raise ToolError(f"registry file {name!r} is not "
                        f"valid UTF-8 text: {exc}")
    if suffix == ".json":
        entries = _load_json_registry(raw, name)
    else:
        entries = _load_csv_registry(raw, name)
    if not entries:
        raise ToolError(f"registry file {name!r} contains no "
                        f"links — nothing to lint")
    return entries


# ---------------------------------------------------------------------------
# per-link checks
# ---------------------------------------------------------------------------

def parse_link(url):
    """One URL -> (parts, pairs, problem): urlsplit parts, the
    query as an ordered (key, value) list, and a malformed
    reason or None. A malformed link gets no further checks —
    its shape is the finding."""
    if any(ch.isspace() for ch in url):
        return None, [], "the URL contains a space"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None, [], "the URL cannot be parsed as written"
    if parts.scheme.lower() not in ("http", "https"):
        if not parts.scheme:
            return None, [], ("missing scheme — a campaign "
                              "link needs http(s):// in front")
        return None, [], (f"scheme {parts.scheme!r} is not "
                          f"http/https — a campaign link must "
                          f"be a web link")
    if not host:
        return None, [], "the URL has no host"
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    return parts, pairs, None


def utm_values(pairs):
    """The query pairs -> {short name: [values in order]} for
    the five standard parameters, keyed by EXACT key only.
    Case-mangled keys are not read as the parameter (that is
    the unknown-param finding's whole point)."""
    values = {name: [] for name in PARAMS}
    for key, value in pairs:
        if key in NAME_OF:
            values[NAME_OF[key]].append(value)
    return values


def check_components(values, config):
    """Convention checks over a {short name: value-or-None}
    mapping — shared by lint (values parsed from a link) and
    build (values given as components). Returns a list of
    (class, reason) findings. Only rules the conventions
    file actually states are checked."""
    findings = []
    if config is None:
        return findings
    for name in config.get("require", []):
        if not values.get(name):
            findings.append((
                "missing-param",
                f"{KEY_OF[name]} is required by the "
                f"conventions file but has no value"))
    for name, field in (("source", "allowed_sources"),
                        ("medium", "allowed_mediums")):
        value = values.get(name)
        allowed = config.get(field)
        if value and allowed is not None:
            if value.casefold() not in \
                    {a.casefold() for a in allowed}:
                findings.append((
                    "not-allowed",
                    f"{KEY_OF[name]} value {value!r} is not "
                    f"in the conventions file's {field} "
                    f"({', '.join(allowed)}) — membership was "
                    f"compared case-insensitively"))
    case = config.get("case")
    if case in ("lower", "upper"):
        for name in PARAMS:
            value = values.get(name)
            if value:
                fixed = value.lower() if case == "lower" \
                    else value.upper()
                if value != fixed:
                    findings.append((
                        "case-violation",
                        f"{KEY_OF[name]} value {value!r} is "
                        f"not {case}case — the conventions "
                        f"file's case rule requires {fixed!r}"))
    campaign_re = config.get("campaign_pattern")
    if campaign_re is not None and values.get("campaign"):
        if not campaign_re.search(values["campaign"]):
            findings.append((
                "pattern-violation",
                f"utm_campaign value "
                f"{values['campaign']!r} does not match the "
                f"conventions file's campaign_pattern "
                f"{config['campaign_pattern_src']}"))
    value_re = config.get("value_pattern")
    if value_re is not None:
        for name in PARAMS:
            value = values.get(name)
            if value and not value_re.search(value):
                findings.append((
                    "pattern-violation",
                    f"{KEY_OF[name]} value {value!r} does "
                    f"not match the conventions file's "
                    f"value_pattern "
                    f"{config['value_pattern_src']}"))
    return findings


def check_link(url, config):
    """One registry URL -> (findings, parsed) where parsed is
    {values, pairs, parts} or None when malformed. Findings
    are (class, reason) in CLASS_ORDER-friendly sequence."""
    parts, pairs, problem = parse_link(url)
    if problem:
        return [("malformed", problem)], None
    findings = []
    values = utm_values(pairs)
    seen_keys = {}
    for key, _value in pairs:
        seen_keys[key] = seen_keys.get(key, 0) + 1
    for key in sorted(seen_keys):
        if key in NAME_OF:
            continue
        if key.casefold() in NAME_OF:
            findings.append((
                "unknown-param",
                f"parameter {key!r} is not {key.casefold()!r}"
                f" — query keys are case-sensitive, so "
                f"analytics reads this as a different, unknown "
                f"parameter and the value is unattributed"))
        elif key.casefold().startswith("utm_"):
            findings.append((
                "unknown-param",
                f"parameter {key!r} is not one of the five "
                f"the UTM scheme defines (utm_source, "
                f"utm_medium, utm_campaign, utm_term, "
                f"utm_content) — analytics will not read it "
                f"as a campaign parameter"))
    if config is not None and "allowed_params" in config:
        allowed_extra = set(config["allowed_params"])
        for key in sorted(seen_keys):
            if key in NAME_OF or key.casefold() in NAME_OF \
                    or key.casefold().startswith("utm_"):
                continue  # the utm_* namespace (any case) is
                # the scheme check's territory, above —
                # allowed_params governs the OTHER keys
            if key not in allowed_extra:
                findings.append((
                    "extra-param",
                    f"query parameter {key!r} is not in the "
                    f"conventions file's allowed_params "
                    f"({', '.join(config['allowed_params'])})"))
    for key in sorted(seen_keys):
        if seen_keys[key] > 1:
            findings.append((
                "repeated-param",
                f"parameter {key!r} appears "
                f"{seen_keys[key]} times in one link — "
                f"different parsers keep different occurrences, "
                f"so which value analytics records is "
                f"ambiguous"))
    # The value convention checks see: the first occurrence
    # (a repeat is its own finding, above); an empty value is
    # no value — a required parameter present-but-empty is
    # missing in every way that matters.
    single = {}
    for name in PARAMS:
        vals = values[name]
        single[name] = vals[0] if vals and vals[0] else None
    findings.extend(check_components(single, config))
    return findings, {"values": values, "pairs": pairs,
                      "parts": parts, "single": single}


# ---------------------------------------------------------------------------
# registry-wide checks
# ---------------------------------------------------------------------------

def normalize_url(url):
    """Canonical form for duplicate comparison: scheme and
    host lowercased, one trailing path slash removed,
    fragment dropped, query kept verbatim. Unparsable URLs
    normalise to their lowercased raw form, so identical
    breakage still groups together."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return url.lower()
    scheme = (parts.scheme or "").lower()
    if not scheme or not host:
        return url.lower()
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    out = f"{scheme}://{host}"
    try:
        if parts.port:
            out += f":{parts.port}"
    except ValueError:
        pass
    out += path
    if parts.query:
        out += f"?{parts.query}"
    return out


def base_of(parts, pairs):
    """The destination a link points at, campaign parameters
    removed: normalised scheme://host/path plus any non-utm
    query pairs, in their original order."""
    kept = [(k, v) for k, v in pairs if k not in NAME_OF]
    out = f"{parts.scheme.lower()}://" \
          f"{(parts.hostname or '').lower()}"
    try:
        if parts.port:
            out += f":{parts.port}"
    except ValueError:
        pass
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    out += path
    if kept:
        out += "?" + urlencode(kept, quote_via=quote)
    return out


def registry_findings(entries, parsed_list):
    """The facts no single link can show: case-drift,
    conflicting duplicates, plain duplicates. Returns a list
    of finding dicts in CLASS_ORDER sequence."""
    findings = []

    # case-drift: per parameter, spellings that differ only
    # by case, across the whole registry.
    for name in PARAMS:
        spellings = {}
        for entry, parsed in zip(entries, parsed_list):
            if parsed is None:
                continue
            for value in parsed["values"][name]:
                if value:
                    slot = spellings.setdefault(
                        value.casefold(), {})
                    slot[value] = slot.get(value, 0) + 1
                    slot.setdefault("__refs__", [])
                    if entry["ref"] not in slot["__refs__"]:
                        slot["__refs__"].append(entry["ref"])
        for folded in sorted(spellings):
            slot = spellings[folded]
            variants = {k: v for k, v in slot.items()
                        if k != "__refs__"}
            if len(variants) > 1:
                detail = ", ".join(
                    f"{spelling!r} ×{count}" for spelling,
                    count in sorted(variants.items()))
                findings.append({
                    "class": "case-drift",
                    "parameter": KEY_OF[name],
                    "spellings": variants,
                    "entries": slot["__refs__"],
                    "reason": f"{KEY_OF[name]} appears as "
                              f"{detail} across the registry "
                              f"— analytics treats each "
                              f"spelling as a different value, "
                              f"so one source silently becomes "
                              f"several rows",
                })

    # conflicting-duplicate: one full attribution signature
    # (source+medium+campaign all present) pointing at two or
    # more different destinations.
    by_signature = {}
    for entry, parsed in zip(entries, parsed_list):
        if parsed is None:
            continue
        single = parsed["single"]
        if not all(single[n] for n in
                   ("source", "medium", "campaign")):
            continue
        signature = tuple(single[n] for n in PARAMS)
        slot = by_signature.setdefault(signature, {})
        base = base_of(parsed["parts"], parsed["pairs"])
        slot.setdefault(base, [])
        if entry["ref"] not in slot[base]:
            slot[base].append(entry["ref"])
    for signature in sorted(by_signature,
                            key=lambda s: [x or "" for x in s]):
        slot = by_signature[signature]
        if len(slot) > 1:
            label = ", ".join(
                f"{KEY_OF[n]}={v}" for n, v in
                zip(PARAMS, signature) if v)
            findings.append({
                "class": "conflicting-duplicate",
                "signature": {KEY_OF[n]: v for n, v in
                              zip(PARAMS, signature) if v},
                "targets": [
                    {"base": base, "entries": refs}
                    for base, refs in sorted(slot.items())],
                "reason": f"the same campaign signature "
                          f"({label}) points at "
                          f"{len(slot)} different destinations "
                          f"— analytics merges them into one "
                          f"campaign, so neither destination's "
                          f"results can be told apart",
            })

    # duplicate: the identical normalised URL registered
    # more than once. Informational — the same link used in
    # several places can be deliberate.
    by_url = {}
    for entry in entries:
        norm = normalize_url(entry["url"])
        by_url.setdefault(norm, []).append(entry["ref"])
    for norm in sorted(by_url):
        refs = by_url[norm]
        if len(refs) > 1:
            findings.append({
                "class": "duplicate",
                "url": norm,
                "entries": refs,
                "reason": f"the identical link is registered "
                          f"{len(refs)} times ({', '.join(refs)})"
                          f" — fine if deliberate; a registry "
                          f"usually wants one entry per link",
            })

    order = {cls: i for i, cls in enumerate(CLASS_ORDER)}
    findings.sort(key=lambda f: order[f["class"]])
    return findings


def analyse(entries, config):
    """The whole registry -> a report dict: per-entry
    findings, registry findings, and the summary counts.
    Pure function of the inputs."""
    per_entry = []
    parsed_list = []
    for entry in entries:
        findings, parsed = check_link(entry["url"], config)
        parsed_list.append(parsed)
        per_entry.append({
            "ref": entry["ref"], "url": entry["url"],
            "findings": findings,
        })
    reg = registry_findings(entries, parsed_list)

    counts = {}
    for entry in per_entry:
        for cls, _reason in entry["findings"]:
            counts[cls] = counts.get(cls, 0) + 1
    for finding in reg:
        counts[finding["class"]] = \
            counts.get(finding["class"], 0) + 1
    by_severity = {"error": 0, "warning": 0, "info": 0}
    for cls, n in counts.items():
        by_severity[SEVERITY[cls]] += n
    summary = {
        "entries": len(entries),
        "unique_links": len({normalize_url(e["url"])
                             for e in entries}),
        "findings_by_class": {
            c: counts[c] for c in CLASS_ORDER if counts.get(c)},
        "errors": by_severity["error"],
        "warnings": by_severity["warning"],
        "infos": by_severity["info"],
        "entries_without_findings": sum(
            1 for e in per_entry if not e["findings"]),
    }
    actionable = by_severity["error"] > 0 or \
        by_severity["warning"] > 0
    return {
        "entries": per_entry,
        "registry_findings": reg,
        "summary": summary,
        "exit_code": 1 if actionable else 0,
    }


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

def validate_base(base):
    """A build base must be an absolute http(s) URL with a
    host and no campaign parameters of its own (the
    components supply those; a base already carrying one
    would duplicate it). Returns (parts, pairs)."""
    parts, pairs, problem = parse_link(base)
    if problem:
        raise ToolError(f"base URL {base!r}: {problem}")
    for key, _value in pairs:
        if key in NAME_OF:
            raise ToolError(
                f"base URL already carries {key!r} — strip "
                f"the campaign parameters from the base and "
                f"pass them as components, or the built link "
                f"would carry the parameter twice")
    return parts, pairs


def assemble(parts, pairs, components):
    """base parts + existing non-utm query pairs + the
    components (in canonical order) -> the built URL.
    Values are percent-encoded; the base is never rewritten
    beyond dropping its fragment (a fragment after a query
    would orphan the parameters from most readers)."""
    query = list(pairs)
    for name in PARAMS:
        value = components.get(name)
        if value:
            query.append((KEY_OF[name], value))
    return urlunsplit((parts.scheme, parts.netloc,
                       parts.path,
                       urlencode(query, quote_via=quote), ""))


def build_one(base, components, config):
    """Validate + assemble one link. Raises ToolError —
    carrying the violations — when the components break the
    conventions file: a governed builder refuses, it does
    not silently fix."""
    parts, pairs = validate_base(base)
    problems = check_components(components, config)
    if problems:
        raise ToolError(
            "the components violate the conventions file: "
            + "; ".join(reason for _cls, reason in problems),
            detail={"violations": [
                {"class": cls, "severity": SEVERITY[cls],
                 "reason": reason} for cls, reason in problems]})
    return assemble(parts, pairs, components)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _finding_json(cls, reason):
    return {"class": cls, "severity": SEVERITY[cls],
            "reason": reason}


def _registry_finding_json(finding):
    out = {"class": finding["class"],
           "severity": SEVERITY[finding["class"]],
           "reason": finding["reason"]}
    for key in ("parameter", "spellings", "entries",
                "signature", "targets", "url"):
        if key in finding:
            out[key] = finding[key]
    return out


def cmd_lint(a):
    entries = load_registry(a.registry)
    config = load_conventions(a.config) if a.config else None
    report = analyse(entries, config)
    name = Path(a.registry).name
    summary = report["summary"]
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__,
            "command": "lint", "registry_file": name,
            "conventions_file": Path(a.config).name
            if a.config else None,
            "conventions": describe_config(config),
            "checks_skipped": CONFIG_CLASSES
            if config is None else [],
            "scope": SCOPE_NOTE,
            "entries": [{
                "ref": e["ref"], "url": e["url"],
                "findings": [_finding_json(c, r)
                             for c, r in e["findings"]],
            } for e in report["entries"]],
            "registry_findings": [
                _registry_finding_json(f)
                for f in report["registry_findings"]],
            "summary": summary,
        }))
        return report["exit_code"]
    print(f"{TOOL} v{__version__} — lint · registry {name}")
    print(f"{summary['entries']} link(s) · "
          f"{summary['unique_links']} unique")
    print("This tool reads text and never fetches a link.")
    if config is None:
        print("No conventions file: only structural checks "
              "and registry-internal")
        print("facts were checked. Skipped (they need YOUR "
              "rules in a --config file):")
        print("  " + ", ".join(CONFIG_CLASSES))
    else:
        print(f"Conventions ({Path(a.config).name}) — the "
              f"rules came from this file:")
        for line in describe_config(config):
            print(f"  {line}")
    print()
    counts = summary["findings_by_class"]
    if counts:
        print("Findings by class:")
        for cls in CLASS_ORDER:
            if cls in counts:
                suffix = " (informational)" \
                    if cls == "duplicate" else ""
                print(f"  {cls}: {counts[cls]}{suffix}")
    else:
        print("Findings: none")
    print(f"Errors: {summary['errors']} · warnings: "
          f"{summary['warnings']} · info: {summary['infos']}")
    print()
    print("Per link:")
    for entry in report["entries"]:
        print(f"  [{entry['ref']}] {entry['url']}")
        if not entry["findings"]:
            print("    no findings")
        for cls, reason in entry["findings"]:
            print(f"    ! {cls} — {reason}")
    if report["registry_findings"]:
        print()
        print("Across the registry:")
        for finding in report["registry_findings"]:
            print(f"  ! {finding['class']} — "
                  f"{finding['reason']}")
    print()
    if report["exit_code"]:
        print("Verdict: ACTION — the findings above are the "
              "worklist; fix them in the registry (or in the "
              "conventions file, if the file is what is wrong).")
    else:
        print("Verdict: CLEAN — every link obeys the checks "
              "that ran. That says the registry is consistent "
              "with the rules given, never that the links load.")
    return report["exit_code"]


def _components_from_args(a):
    return {"source": a.source, "medium": a.medium,
            "campaign": a.campaign, "term": a.term,
            "content": a.content}


def cmd_build(a):
    config = load_conventions(a.config) if a.config else None
    components = _components_from_args(a)
    url = build_one(a.base, components, config)
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__,
            "command": "build",
            "conventions_file": Path(a.config).name
            if a.config else None,
            "url": url,
            "params": {KEY_OF[n]: components[n]
                       for n in PARAMS if components.get(n)},
            "scope": SCOPE_NOTE,
        }))
    else:
        print(url)
    return 0


BATCH_COLUMNS = ["base", "source", "medium", "campaign",
                 "term", "content", "label"]


def load_batch(path):
    """A build-batch CSV -> a list of row dicts. The header
    must carry base/source/medium/campaign; term, content and
    label are optional columns. Blank component cells are
    simply absent."""
    name = Path(path).name
    if Path(path).suffix.lower() != ".csv":
        raise ToolError(f"batch file {name!r}: build-batch "
                        f"reads a .csv file")
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ToolError(f"cannot read batch file {path!r}: "
                        f"{exc}")
    except UnicodeDecodeError as exc:
        raise ToolError(f"batch file {name!r} is not valid "
                        f"UTF-8 text: {exc}")
    try:
        rows = list(csv.reader(io.StringIO(raw), strict=True))
    except csv.Error as exc:
        raise ToolError(f"batch file {name!r} is not valid "
                        f"CSV: {exc}")
    if not rows:
        raise ToolError(f"batch file {name!r}: the CSV has "
                        f"no header row")
    header = [h.strip().lower() for h in rows[0]]
    missing = [c for c in ("base", "source", "medium",
                           "campaign") if c not in header]
    if missing:
        raise ToolError(
            f"batch file {name!r}: the CSV is missing "
            f"column(s): {', '.join(missing)} (header is: "
            f"{', '.join(rows[0])})")
    out = []
    for i, row in enumerate(rows[1:]):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise ToolError(
                f"batch file {name!r}: row {i + 2} has "
                f"{len(row)} field(s), the header has "
                f"{len(header)}")
        record = dict(zip(header, row))
        entry = {"ref": f"row {i + 2}"}
        label = (record.get("label") or "").strip()
        if label:
            entry["ref"] = label
        entry["base"] = record["base"].strip()
        entry["components"] = {
            n: (record.get(n) or "").strip() or None
            for n in PARAMS}
        out.append(entry)
    if not out:
        raise ToolError(f"batch file {name!r} contains no "
                        f"rows — nothing to build")
    return out


def cmd_build_batch(a):
    rows = load_batch(a.batch)
    config = load_conventions(a.config) if a.config else None
    built, refused = [], []
    for row in rows:
        try:
            url = build_one(row["base"], row["components"],
                            config)
        except ToolError as exc:
            refused.append({
                "ref": row["ref"],
                "violations": exc.detail.get(
                    "violations",
                    [{"class": "invalid-row", "severity":
                      "error", "reason": str(exc)}]),
                "error": str(exc),
            })
            continue
        built.append({"ref": row["ref"], "url": url})
    exit_code = 1 if refused else 0
    if a.json:
        print(json.dumps({
            "tool": TOOL, "version": __version__,
            "command": "build-batch",
            "batch_file": Path(a.batch).name,
            "conventions_file": Path(a.config).name
            if a.config else None,
            "built": built,
            "refused": [{k: r[k] for k in
                         ("ref", "violations")}
                        for r in refused],
            "summary": {"rows": len(rows),
                        "built": len(built),
                        "refused": len(refused)},
            "scope": SCOPE_NOTE,
        }))
        return exit_code
    print(f"{TOOL} v{__version__} — build-batch · "
          f"{Path(a.batch).name}")
    print(f"{len(rows)} row(s) · {len(built)} built · "
          f"{len(refused)} refused")
    print()
    for item in built:
        print(f"  [{item['ref']}] {item['url']}")
    for item in refused:
        print(f"  [{item['ref']}] REFUSED — {item['error']}")
    return exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class _JsonAwareParser(argparse.ArgumentParser):
    """ArgumentParser that reports usage errors as JSON in
    --json mode ({"error": ...} on stdout, same exit code 2)
    — an agent driving this tool with --json never gets
    plain text or a traceback. The flag lives on the class
    so subparsers share it."""

    json_mode = False

    def error(self, message):
        if self.json_mode:
            print(json.dumps({"error": message}))
            self.exit(2)
        super().error(message)


def _json_arg(p):
    p.add_argument("--json", action="store_true",
                   help="one JSON object instead of text output")


def _config_arg(p):
    p.add_argument("--config",
                   help="conventions file (JSON) — the rules "
                        "to enforce; without one, only "
                        "structural and registry-internal "
                        "checks run")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Govern campaign links: lint a link "
                    "registry against your own conventions "
                    "file, and build new links that obey it "
                    "(stdlib only, local only, never fetches "
                    "a URL).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_lint = sub.add_parser(
        "lint", help="check every link in a registry against "
                     "the conventions file and the "
                     "registry's own consistency")
    p_lint.add_argument("registry",
                        help="registry file (.json or .csv)")
    _config_arg(p_lint)
    _json_arg(p_lint)
    p_lint.set_defaults(func=cmd_lint)

    p_build = sub.add_parser(
        "build", help="assemble one link from components, "
                      "validated against the conventions "
                      "file when one is given")
    p_build.add_argument("--base", required=True,
                         help="destination URL (no utm_* "
                              "parameters of its own)")
    p_build.add_argument("--source", required=True)
    p_build.add_argument("--medium", required=True)
    p_build.add_argument("--campaign", required=True)
    p_build.add_argument("--term")
    p_build.add_argument("--content")
    _config_arg(p_build)
    _json_arg(p_build)
    p_build.set_defaults(func=cmd_build)

    p_batch = sub.add_parser(
        "build-batch", help="build one link per CSV row "
                            "(base, source, medium, campaign, "
                            "term, content, label)")
    p_batch.add_argument("batch", help="batch file (.csv)")
    _config_arg(p_batch)
    _json_arg(p_batch)
    p_batch.set_defaults(func=cmd_build_batch)

    a = ap.parse_args(argv)

    def fail(exc):
        if getattr(a, "json", False):
            payload = {"error": str(exc)}
            payload.update(exc.detail)
            print(json.dumps(payload))
        else:
            print(f"ERROR: {exc}")
        return 2

    try:
        return a.func(a)
    except ToolError as exc:
        return fail(exc)
    except BrokenPipeError:
        return 2


if __name__ == "__main__":
    sys.exit(main())
