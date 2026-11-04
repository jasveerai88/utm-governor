#!/usr/bin/env python3
"""Tests for utm-governor. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

Expectations are worked out from the fixtures by hand, not
copied from the tool's own output:

- The bundled sample (examples/sample-registry.json) carries
  9 fictional links against examples/conventions.json
  (case=lower; require source/medium/campaign; sources
  youtube/instagram/newsletter/partner-blog; mediums
  social/email/cpc/referral; campaign pattern
  ^[a-z0-9]+(-[a-z0-9]+)*$; value pattern ^[A-Za-z0-9.-]+$;
  allowed extra param: ref). One planted fault per class:
    winter-sale-shorts    utm_source=YouTube -> case-violation
    launch-email          no utm_campaign    -> missing-param
    typo-param            utm_campagin       -> unknown-param
    off-list-source       utm_source=tiktok  -> not-allowed
    underscored-campaign  winter_sale breaks BOTH patterns
                                             -> pattern-violation x2
    registry-wide         youtube/YouTube    -> case-drift
                          spring-promo signature on /pricing
                          AND /deals         -> conflicting-duplicate
                          winter-sale-video registered twice
                                             -> duplicate (info)
  Findings: 9 total = 8 errors + 1 info; findings_by_class
  {unknown-param 1, missing-param 1, not-allowed 1,
  case-violation 1, pattern-violation 2, case-drift 1,
  conflicting-duplicate 1, duplicate 1}. 9 entries, 8 unique
  links, 4 entries without per-link findings (winter-sale-
  video, spring-promo-pricing, spring-promo-deals,
  winter-sale-video-copy). Exit 1.
- The SAME registry without --config: only the checks that
  need no one's rules may fire — unknown-param 1,
  case-drift 1, conflicting-duplicate 1, duplicate 1 = 4
  findings (3 errors + 1 info), exit 1, and the JSON names
  the five config-gated classes as skipped.
- The clean CSV against the same conventions: 0 findings,
  exit 0.
- The batch fixture: 3 rows; rows 1-2 build to URLs derived
  by hand below; row 3 (tiktok) is refused on not-allowed.
  Exit 1.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parents[1]
TOOL = PACK_ROOT / "src" / "utm_governor.py"
SAMPLE = PACK_ROOT / "examples" / "sample-registry.json"
CLEAN = PACK_ROOT / "examples" / "clean-registry.csv"
CONVENTIONS = PACK_ROOT / "examples" / "conventions.json"
BATCH = PACK_ROOT / "examples" / "batch.csv"

SHOP = "https://focusbrilliant.example/shop"


def run(args, cwd):
    return subprocess.run([sys.executable, str(TOOL)] + args,
                          capture_output=True, text=True, cwd=cwd)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_json(self, obj, name="registry.json"):
        path = self.dir / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def write_text(self, text, name):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def lint_json(self, *args):
        proc = run(["lint", *args, "--json"], self.dir)
        return proc, json.loads(proc.stdout)

    def one_link(self, url, config=None):
        """Lint a one-link JSON registry; return the parsed
        report (and the process)."""
        path = self.write_json([url])
        args = [str(path)]
        if config is not None:
            cfg = self.write_json(config, "conventions.json")
            args += ["--config", str(cfg)]
        return self.lint_json(*args)

    def classes_of(self, data, ref):
        entry = next(e for e in data["entries"]
                     if e["ref"] == ref)
        return [f["class"] for f in entry["findings"]]


class SampleLintTest(TempDirTest):
    def test_sample_summary_counts(self):
        proc, data = self.lint_json(
            str(SAMPLE), "--config", str(CONVENTIONS))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(data["tool"], "utm-governor")
        self.assertEqual(data["command"], "lint")
        self.assertEqual(data["checks_skipped"], [])
        summary = data["summary"]
        self.assertEqual(summary["entries"], 9)
        self.assertEqual(summary["unique_links"], 8)
        self.assertEqual(summary["findings_by_class"], {
            "unknown-param": 1, "missing-param": 1,
            "not-allowed": 1, "case-violation": 1,
            "pattern-violation": 2, "case-drift": 1,
            "conflicting-duplicate": 1, "duplicate": 1})
        self.assertEqual(summary["errors"], 8)
        self.assertEqual(summary["warnings"], 0)
        self.assertEqual(summary["infos"], 1)
        self.assertEqual(
            summary["entries_without_findings"], 4)

    def test_sample_per_link_findings(self):
        _proc, data = self.lint_json(
            str(SAMPLE), "--config", str(CONVENTIONS))
        self.assertEqual(
            self.classes_of(data, "winter-sale-video"), [])
        self.assertEqual(
            self.classes_of(data, "winter-sale-shorts"),
            ["case-violation"])
        self.assertEqual(
            self.classes_of(data, "launch-email"),
            ["missing-param"])
        self.assertEqual(
            self.classes_of(data, "typo-param"),
            ["unknown-param"])
        self.assertEqual(
            self.classes_of(data, "off-list-source"),
            ["not-allowed"])
        self.assertEqual(
            self.classes_of(data, "underscored-campaign"),
            ["pattern-violation", "pattern-violation"])
        self.assertEqual(
            self.classes_of(data, "spring-promo-pricing"), [])
        self.assertEqual(
            self.classes_of(data, "spring-promo-deals"), [])

    def test_sample_registry_findings(self):
        _proc, data = self.lint_json(
            str(SAMPLE), "--config", str(CONVENTIONS))
        reg = data["registry_findings"]
        self.assertEqual([f["class"] for f in reg],
                         ["case-drift", "conflicting-duplicate",
                          "duplicate"])
        drift = reg[0]
        self.assertEqual(drift["parameter"], "utm_source")
        self.assertEqual(drift["spellings"],
                         {"YouTube": 1, "youtube": 2})
        conflict = reg[1]
        self.assertEqual(conflict["signature"], {
            "utm_source": "partner-blog",
            "utm_medium": "referral",
            "utm_campaign": "spring-promo"})
        self.assertEqual(
            {t["base"] for t in conflict["targets"]},
            {"https://focusbrilliant.example/pricing",
             "https://focusbrilliant.example/deals"})
        self.assertEqual(reg[2]["severity"], "info")

    def test_sample_without_config_skips_governed_checks(self):
        proc, data = self.lint_json(str(SAMPLE))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(data["checks_skipped"], [
            "missing-param", "not-allowed", "extra-param",
            "case-violation", "pattern-violation"])
        self.assertEqual(data["summary"]["findings_by_class"], {
            "unknown-param": 1, "case-drift": 1,
            "conflicting-duplicate": 1, "duplicate": 1})
        self.assertEqual(data["summary"]["errors"], 3)
        self.assertEqual(data["summary"]["infos"], 1)
        # tiktok and YouTube pass unjudged — no rules were given
        self.assertEqual(
            self.classes_of(data, "off-list-source"), [])
        self.assertEqual(
            self.classes_of(data, "winter-sale-shorts"), [])

    def test_clean_csv_exits_zero(self):
        proc, data = self.lint_json(
            str(CLEAN), "--config", str(CONVENTIONS))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(data["summary"]["entries"], 3)
        self.assertEqual(data["summary"]["findings_by_class"],
                         {})
        self.assertEqual(data["registry_findings"], [])

    def test_json_recounts_against_text(self):
        """The summary must be derivable from the findings
        actually listed — recount both ways."""
        _proc, data = self.lint_json(
            str(SAMPLE), "--config", str(CONVENTIONS))
        recounted = {}
        total = 0
        for entry in data["entries"]:
            for finding in entry["findings"]:
                recounted[finding["class"]] = \
                    recounted.get(finding["class"], 0) + 1
                total += 1
        for finding in data["registry_findings"]:
            recounted[finding["class"]] = \
                recounted.get(finding["class"], 0) + 1
            total += 1
        self.assertEqual(recounted,
                         data["summary"]["findings_by_class"])
        self.assertEqual(total, 9)
        proc = run(["lint", str(SAMPLE), "--config",
                    str(CONVENTIONS)], self.dir)
        self.assertEqual(proc.returncode, 1)
        for cls, n in recounted.items():
            self.assertIn(f"{cls}: {n}", proc.stdout)


class PerLinkRuleTest(TempDirTest):
    FULL = ("?utm_source=youtube&utm_medium=social"
            "&utm_campaign=spring-launch")

    def test_malformed_variants(self):
        for url in ("focusbrilliant.example/shop",     # no scheme
                    "https://",                          # no host
                    "https://exa mple.com/shop",         # space
                    "ftp://focusbrilliant.example/x"):   # scheme
            proc, data = self.one_link(url)
            self.assertEqual(proc.returncode, 1, url)
            self.assertEqual(
                self.classes_of(data, "links[0]"),
                ["malformed"], url)

    def test_wellformed_link_is_quiet_without_config(self):
        proc, data = self.one_link(SHOP + self.FULL)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(data["summary"]["findings_by_class"],
                         {})

    def test_unknown_param_typo(self):
        proc, data = self.one_link(
            SHOP + "?utm_source=youtube&utm_medium=social"
                   "&utm_campagin=spring")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["unknown-param"])

    def test_unknown_param_key_case(self):
        _proc, data = self.one_link(
            SHOP + "?UTM_Source=youtube&utm_medium=social"
                   "&utm_campaign=spring")
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["unknown-param"])

    def test_missing_param_needs_config(self):
        config = {"require": ["source", "medium", "campaign"]}
        proc, data = self.one_link(
            SHOP + "?utm_source=youtube&utm_medium=social",
            config)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["missing-param"])
        # and without the config, silence — no rule, no finding
        proc2, data2 = self.one_link(
            SHOP + "?utm_source=youtube&utm_medium=social")
        self.assertEqual(proc2.returncode, 0)
        self.assertEqual(self.classes_of(data2, "links[0]"), [])

    def test_missing_param_present_but_empty(self):
        config = {"require": ["campaign"]}
        _proc, data = self.one_link(
            SHOP + "?utm_source=youtube&utm_medium=social"
                   "&utm_campaign=", config)
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["missing-param"])

    def test_not_allowed_source_and_medium(self):
        config = {"allowed_sources": ["youtube"],
                  "allowed_mediums": ["social"]}
        _proc, data = self.one_link(
            SHOP + "?utm_source=vimeo&utm_medium=banner"
                   "&utm_campaign=spring", config)
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["not-allowed", "not-allowed"])
        # membership is case-insensitive: YouTube IS youtube
        _proc2, data2 = self.one_link(
            SHOP + "?utm_source=YouTube&utm_medium=social"
                   "&utm_campaign=spring", config)
        self.assertEqual(self.classes_of(data2, "links[0]"), [])

    def test_extra_param_only_when_configured(self):
        config = {"allowed_params": ["ref"]}
        _proc, data = self.one_link(
            SHOP + self.FULL + "&gclid=abc123", config)
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["extra-param"])
        _proc2, data2 = self.one_link(
            SHOP + self.FULL + "&ref=partner42", config)
        self.assertEqual(self.classes_of(data2, "links[0]"), [])
        _proc3, data3 = self.one_link(
            SHOP + self.FULL + "&gclid=abc123")
        self.assertEqual(self.classes_of(data3, "links[0]"), [])

    def test_case_rule_lower_upper_any(self):
        url = SHOP + "?utm_source=YouTube&utm_medium=social" \
                     "&utm_campaign=spring"
        _p, d = self.one_link(url, {"case": "lower"})
        self.assertEqual(self.classes_of(d, "links[0]"),
                         ["case-violation"])
        _p, d = self.one_link(url, {"case": "any"})
        self.assertEqual(self.classes_of(d, "links[0]"), [])
        _p, d = self.one_link(url, {"case": "upper"})
        # source YouTube, medium social, campaign spring —
        # all three fail "must be upper"
        self.assertEqual(self.classes_of(d, "links[0]"),
                         ["case-violation"] * 3)

    def test_pattern_rules(self):
        config = {"campaign_pattern": "^[a-z0-9-]+$",
                  "value_pattern": "^[A-Za-z0-9.-]+$"}
        # winter_sale breaks the campaign pattern (underscore,
        # not a hyphenated slug) AND the value pattern
        # (underscore is outside its character set): 2 findings
        _p, d = self.one_link(
            SHOP + "?utm_source=youtube&utm_medium=social"
                   "&utm_campaign=spring_sale", config)
        self.assertEqual(self.classes_of(d, "links[0]"),
                         ["pattern-violation",
                          "pattern-violation"])
        _p, d = self.one_link(SHOP + self.FULL, config)
        self.assertEqual(self.classes_of(d, "links[0]"), [])

    def test_repeated_param_is_a_warning(self):
        url = (SHOP + "?utm_source=youtube&utm_source=yt"
                      "&utm_medium=social&utm_campaign=spring")
        proc, data = self.one_link(url)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.classes_of(data, "links[0]"),
                         ["repeated-param"])
        self.assertEqual(data["summary"]["warnings"], 1)
        self.assertEqual(data["summary"]["errors"], 0)


class RegistryRuleTest(TempDirTest):
    def two_links(self, urls, config=None):
        path = self.write_json(urls)
        args = [str(path)]
        if config is not None:
            cfg = self.write_json(config, "conventions.json")
            args += ["--config", str(cfg)]
        return self.lint_json(*args)

    def test_case_drift_needs_two_spellings(self):
        a = SHOP + "?utm_source=youtube&utm_medium=social" \
                   "&utm_campaign=spring"
        b = SHOP + "?utm_source=YouTube&utm_medium=social" \
                   "&utm_campaign=summer"
        _p, d = self.two_links([a, b])
        self.assertEqual(
            [f["class"] for f in d["registry_findings"]],
            ["case-drift"])
        # same spelling twice: no drift (and the campaign
        # differs, so no conflict either)
        _p, d2 = self.two_links([a, a.replace("spring",
                                              "summer")])
        self.assertEqual(d2["registry_findings"], [])

    def test_conflict_needs_two_destinations(self):
        sig = "?utm_source=youtube&utm_medium=social" \
              "&utm_campaign=spring"
        _p, d = self.two_links([SHOP + sig,
                                "https://focusbrilliant.example"
                                "/deals" + sig])
        self.assertEqual(
            [f["class"] for f in d["registry_findings"]],
            ["conflicting-duplicate"])
        # same signature, SAME destination: a plain duplicate
        proc, d2 = self.two_links([SHOP + sig, SHOP + sig])
        self.assertEqual(
            [f["class"] for f in d2["registry_findings"]],
            ["duplicate"])
        # an info-only registry exits 0
        self.assertEqual(proc.returncode, 0)

    def test_conflict_needs_full_signature(self):
        # no campaign -> not an attribution signature, even
        # with two destinations and matching source/medium
        partial = "?utm_source=youtube&utm_medium=social"
        _p, d = self.two_links(
            [SHOP + partial,
             "https://focusbrilliant.example/deals" + partial])
        self.assertEqual(d["registry_findings"], [])

    def test_plain_duplicate_is_info_only(self):
        url = SHOP + "?utm_source=youtube&utm_medium=social" \
                     "&utm_campaign=spring"
        proc, data = self.two_links([url, url])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(data["summary"]["infos"], 1)
        self.assertEqual(data["summary"]["errors"], 0)


class ConventionsValidationTest(TempDirTest):
    def assert_config_error(self, config_obj=None, raw=None):
        if raw is not None:
            cfg = self.write_text(raw, "conventions.json")
        else:
            cfg = self.write_json(config_obj,
                                  "conventions.json")
        reg = self.write_json([SHOP])
        proc = run(["lint", str(reg), "--config", str(cfg),
                    "--json"], self.dir)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))
        self.assertNotIn("Traceback", proc.stderr)

    def test_unknown_rule_key_fails_loudly(self):
        self.assert_config_error({"allowed_source": ["x"]})

    def test_bad_case_value(self):
        self.assert_config_error({"case": "mixed"})

    def test_unknown_require_name(self):
        self.assert_config_error({"require": ["channel"]})

    def test_invalid_regex(self):
        self.assert_config_error({"campaign_pattern": "^(["})

    def test_wrong_types(self):
        self.assert_config_error({"require": "source"})
        self.assert_config_error(
            {"allowed_sources": "youtube"})
        self.assert_config_error(raw='["not", "an", "object"]')
        self.assert_config_error(raw="{not json")


class InputErrorTest(TempDirTest):
    def assert_error(self, args):
        proc = run(args + ["--json"], self.dir)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("error", json.loads(proc.stdout))
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)

    def test_missing_registry(self):
        self.assert_error(["lint", "nope.json"])

    def test_bad_extension(self):
        path = self.write_text("[]", "registry.txt")
        self.assert_error(["lint", str(path)])

    def test_invalid_json_registry(self):
        path = self.write_text("{nope", "registry.json")
        self.assert_error(["lint", str(path)])

    def test_registry_object_without_links_key(self):
        path = self.write_json({"videos": []})
        self.assert_error(["lint", str(path)])

    def test_entry_wrong_shape(self):
        path = self.write_json([{"label": "no url here"}])
        self.assert_error(["lint", str(path)])
        path = self.write_json([42])
        self.assert_error(["lint", str(path)])

    def test_empty_registry(self):
        path = self.write_json([])
        self.assert_error(["lint", str(path)])

    def test_csv_without_url_column(self):
        path = self.write_text("link\nhttps://x.example/\n",
                               "registry.csv")
        self.assert_error(["lint", str(path)])

    def test_csv_ragged_row(self):
        path = self.write_text(
            "label,url\nonly-one-field\n", "registry.csv")
        self.assert_error(["lint", str(path)])

    def test_missing_config_file(self):
        reg = self.write_json([SHOP])
        self.assert_error(["lint", str(reg), "--config",
                           "nope.json"])

    def test_argparse_error_is_json(self):
        proc = run(["lint", "--json"], self.dir)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))
        self.assertNotIn("Traceback", proc.stderr)


class BuildTest(TempDirTest):
    def build(self, *args):
        return run(["build", *args], self.dir)

    def test_build_canonical_order_and_encoding(self):
        proc = self.build(
            "--base", SHOP, "--source", "youtube",
            "--medium", "social", "--campaign", "winter-sale",
            "--content", "end card")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(
            proc.stdout.strip(),
            SHOP + "?utm_source=youtube&utm_medium=social"
                   "&utm_campaign=winter-sale"
                   "&utm_content=end%20card")

    def test_build_keeps_existing_non_utm_query(self):
        proc = self.build(
            "--base", SHOP + "?range=home", "--source",
            "youtube", "--medium", "social", "--campaign",
            "winter-sale")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(
            proc.stdout.strip(),
            SHOP + "?range=home&utm_source=youtube"
                   "&utm_medium=social&utm_campaign=winter-sale")

    def test_build_json_shape(self):
        proc = self.build(
            "--base", SHOP, "--source", "youtube",
            "--medium", "social", "--campaign", "winter-sale",
            "--json")
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data["command"], "build")
        self.assertEqual(data["params"], {
            "utm_source": "youtube", "utm_medium": "social",
            "utm_campaign": "winter-sale"})

    def test_build_refuses_case_violation(self):
        cfg = self.write_json({"case": "lower"},
                              "conventions.json")
        proc = self.build(
            "--base", SHOP, "--source", "YouTube",
            "--medium", "social", "--campaign", "winter-sale",
            "--config", str(cfg), "--json")
        self.assertEqual(proc.returncode, 2)
        data = json.loads(proc.stdout)
        self.assertIn("error", data)
        self.assertEqual([v["class"] for v in
                          data["violations"]],
                         ["case-violation"])
        self.assertNotIn("Traceback", proc.stderr)

    def test_build_refuses_missing_required_term(self):
        cfg = self.write_json(
            {"require": ["source", "medium", "campaign",
                         "term"]}, "conventions.json")
        proc = self.build(
            "--base", SHOP, "--source", "youtube",
            "--medium", "social", "--campaign", "winter-sale",
            "--config", str(cfg))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("ERROR", proc.stdout)

    def test_build_rejects_base_with_utm(self):
        proc = self.build(
            "--base", SHOP + "?utm_source=old", "--source",
            "youtube", "--medium", "social", "--campaign",
            "winter-sale", "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))
        self.assertNotIn("Traceback", proc.stderr)

    def test_build_rejects_bad_base(self):
        proc = self.build(
            "--base", "not a url", "--source", "youtube",
            "--medium", "social", "--campaign", "winter-sale",
            "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))


class BuildBatchTest(TempDirTest):
    def test_batch_fixture(self):
        proc = run(["build-batch", str(BATCH), "--config",
                    str(CONVENTIONS), "--json"], self.dir)
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual(data["summary"],
                         {"rows": 3, "built": 2, "refused": 1})
        self.assertEqual(data["built"], [
            {"ref": "video-main",
             "url": SHOP + "?utm_source=youtube"
                           "&utm_medium=social"
                           "&utm_campaign=winter-sale-2026"},
            {"ref": "video-endcard",
             "url": SHOP + "?utm_source=youtube"
                           "&utm_medium=social"
                           "&utm_campaign=winter-sale-2026"
                           "&utm_content=end-card"}])
        self.assertEqual(data["refused"][0]["ref"],
                         "bad-source")
        self.assertEqual(
            [v["class"] for v in
             data["refused"][0]["violations"]],
            ["not-allowed"])

    def test_batch_all_clean_exits_zero(self):
        path = self.write_text(
            "base,source,medium,campaign\n"
            f"{SHOP},youtube,social,winter-sale-2026\n",
            "batch.csv")
        proc = run(["build-batch", str(path), "--config",
                    str(CONVENTIONS)], self.dir)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("1 built · 0 refused", proc.stdout)

    def test_batch_missing_column_is_error(self):
        path = self.write_text(
            "base,source,medium\n"
            f"{SHOP},youtube,social\n", "batch.csv")
        proc = run(["build-batch", str(path), "--json"],
                   self.dir)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))
        self.assertNotIn("Traceback", proc.stderr)

    def test_batch_bad_base_row_refused_not_fatal(self):
        path = self.write_text(
            "label,base,source,medium,campaign\n"
            f"good,{SHOP},youtube,social,winter-sale\n"
            "bad,notaurl,youtube,social,winter-sale\n",
            "batch.csv")
        proc = run(["build-batch", str(path), "--json"],
                   self.dir)
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual(data["summary"]["built"], 1)
        self.assertEqual(data["summary"]["refused"], 1)
        self.assertEqual(data["refused"][0]["ref"], "bad")


class GuardTest(unittest.TestCase):
    def test_source_has_no_network_code(self):
        source = TOOL.read_text(encoding="utf-8")
        for banned in ("urllib.request", "urlopen",
                       "http.client", "import socket",
                       "import requests"):
            self.assertNotIn(banned, source)

    def test_text_output_states_scope(self):
        proc = run(["lint", str(CLEAN), "--config",
                    str(CONVENTIONS)], PACK_ROOT)
        self.assertIn("never fetches", proc.stdout)


if __name__ == "__main__":
    unittest.main()
