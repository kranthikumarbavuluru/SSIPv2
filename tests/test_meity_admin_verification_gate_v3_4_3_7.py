from __future__ import annotations

import importlib.util
import tempfile
import unittest
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "meity_admin_verification_gate_v3_4_3_7.py"
SPEC = importlib.util.spec_from_file_location("meity_gate_v3437", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)


class MeityAdminVerificationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ssip-v3437-test-")
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir(parents=True)
        GATE.build_self_test_fixture(self.root)
        self.output = self.root / "data/departments/meity/v3_4_3_7"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self):
        return GATE.prepare(self.root, self.output)

    def decision_path(self) -> Path:
        return GATE.output_paths(self.output)["decisions"]

    def set_decisions(self, values: list[tuple[str, str]]) -> Path:
        path = self.decision_path()
        fields, rows = GATE.read_csv(path)
        for row, (decision, reason) in zip(rows, values, strict=True):
            row["admin_decision"] = decision
            row["admin_reason"] = reason
            row["admin_name"] = "Admin"
            row["reviewed_at"] = "2026-07-13T00:00:00+00:00"
        GATE.write_csv(path, fields, rows)
        return path

    def refresh_manifest(self) -> None:
        path = self.root / "data/departments/meity/v3_4_3_4/meity_release_readiness_manifest_v3_4_3_4.json"
        payload = GATE.read_json(path)
        for item in payload["outputs"]:
            output = self.root / item["path"]
            item["sha256"] = GATE.sha256_file(output)
            item["size_bytes"] = output.stat().st_size
        GATE.write_json(path, payload)

    def mutate_candidate(self, mutator) -> None:
        path = self.root / "data/catalogue_preview/v3_4_3_4/catalogue_preview_v3_4_3_4.csv"
        fields, rows = GATE.read_csv(path)
        mutator(rows)
        GATE.write_csv(path, fields, rows)
        self.refresh_manifest()


    def test_recorded_absolute_paths_are_remapped_to_current_checkout(self) -> None:
        summary_path = self.root / "data/departments/meity/v3_4_3_4/meity_release_readiness_summary_v3_4_3_4.json"
        summary = GATE.read_json(summary_path)
        summary["active_catalogue"] = r"D:\WebSite\DASHBOARD\Code\SSIP\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv"
        summary["candidate_catalogue"] = r"D:\WebSite\DASHBOARD\Code\SSIP\data\catalogue_preview\v3_4_3_4\catalogue_preview_v3_4_3_4.csv"
        GATE.write_json(summary_path, summary)
        self.refresh_manifest()
        result = self.prepare()
        self.assertEqual(result.status, "WAITING_FOR_ADMIN")

    def test_prepare_current_baseline(self) -> None:
        result = self.prepare()
        self.assertEqual(result.status, "WAITING_FOR_ADMIN")
        self.assertEqual(result.summary["counts"]["active_raw_rows"], 139)
        self.assertEqual(result.summary["counts"]["candidate_raw_rows"], 141)
        self.assertEqual(result.summary["counts"]["active_dashboard_schemes"], 53)
        self.assertEqual(result.summary["counts"]["candidate_dashboard_schemes"], 55)

    def test_exactly_two_expected_candidates(self) -> None:
        self.prepare()
        _, rows = GATE.read_csv(GATE.output_paths(self.output)["queue"])
        self.assertEqual({row["master_id"] for row in rows}, GATE.TARGET_IDS)
        self.assertEqual(len(rows), 2)

    def test_sasact_and_genesis_appear_once(self) -> None:
        self.prepare()
        _, rows = GATE.read_csv(GATE.output_paths(self.output)["queue"])
        ids = [row["master_id"] for row in rows]
        self.assertEqual(ids.count(GATE.SASACT_ID), 1)
        self.assertEqual(ids.count(GATE.GENESIS_ID), 1)

    def test_missing_decisions_wait(self) -> None:
        result = self.prepare()
        self.assertEqual(result.summary["counts"]["pending"], 2)
        self.assertEqual(result.status, "WAITING_FOR_ADMIN")

    def test_two_approvals_produce_approved_delta(self) -> None:
        self.prepare()
        decisions = self.set_decisions([("APPROVE", ""), ("APPROVE", "")])
        result = GATE.evaluate(self.root, self.output, decisions)
        self.assertEqual(result.status, "PASS")
        _, rows = GATE.read_csv(GATE.output_paths(self.output)["approved"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["publication_eligible"] == "true" for row in rows))
        self.assertTrue(all(row["published"] == "false" for row in rows))

    def test_rejection_excluded_from_approved(self) -> None:
        self.prepare()
        decisions = self.set_decisions([("APPROVE", ""), ("REJECT", "Not suitable")])
        GATE.evaluate(self.root, self.output, decisions)
        _, approved = GATE.read_csv(GATE.output_paths(self.output)["approved"])
        _, rejected = GATE.read_csv(GATE.output_paths(self.output)["rejected"])
        self.assertEqual(len(approved), 1)
        self.assertEqual(len(rejected), 1)

    def test_return_requires_reason(self) -> None:
        self.prepare()
        decisions = self.set_decisions([("RETURN_FOR_CORRECTION", ""), ("APPROVE", "")])
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, decisions)

    def test_defer_requires_reason(self) -> None:
        self.prepare()
        decisions = self.set_decisions([("DEFER", ""), ("APPROVE", "")])
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, decisions)

    def test_unknown_decision_fails(self) -> None:
        self.prepare()
        decisions = self.set_decisions([("YES", ""), ("APPROVE", "")])
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, decisions)

    def test_duplicate_review_id_fails(self) -> None:
        self.prepare()
        path = self.decision_path()
        fields, rows = GATE.read_csv(path)
        rows[1]["review_id"] = rows[0]["review_id"]
        GATE.write_csv(path, fields, rows)
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, path)

    def test_unknown_review_id_fails(self) -> None:
        self.prepare()
        path = self.decision_path()
        fields, rows = GATE.read_csv(path)
        rows[0]["review_id"] = "UNKNOWN"
        GATE.write_csv(path, fields, rows)
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, path)

    def test_candidate_hash_mismatch_fails(self) -> None:
        self.prepare()
        path = self.decision_path()
        fields, rows = GATE.read_csv(path)
        rows[0]["candidate_row_hash"] = "0" * 64
        GATE.write_csv(path, fields, rows)
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, path)

    def test_evidence_hash_mismatch_fails(self) -> None:
        self.prepare()
        path = self.decision_path()
        fields, rows = GATE.read_csv(path)
        rows[0]["evidence_hash"] = "0" * 64
        GATE.write_csv(path, fields, rows)
        with self.assertRaises(GATE.GateError):
            GATE.evaluate(self.root, self.output, path)

    def test_existing_decision_file_is_preserved(self) -> None:
        self.prepare()
        path = self.set_decisions([("APPROVE", "Reviewed"), ("DEFER", "Awaiting evidence")])
        before = path.read_bytes()
        self.prepare()
        self.assertEqual(path.read_bytes(), before)

    def test_rerun_is_deterministic(self) -> None:
        self.prepare()
        paths = GATE.output_paths(self.output)
        selected = [paths[name] for name in ("queue", "decisions", "evidence", "calls", "summary", "gate", "manifest")]
        before = {path.name: GATE.sha256_file(path) for path in selected}
        self.prepare()
        after = {path.name: GATE.sha256_file(path) for path in selected}
        self.assertEqual(before, after)

    def test_permanent_identity_is_preserved(self) -> None:
        self.prepare()
        _, rows = GATE.read_csv(GATE.output_paths(self.output)["queue"])
        self.assertTrue(all(row["permanent_scheme_or_call"] == "PERMANENT_SCHEME" for row in rows))
        self.assertTrue(all(row["call_identity_check_status"] == "PASS" for row in rows))

    def test_call_cannot_replace_permanent_scheme(self) -> None:
        def mutate(rows):
            rows[-1]["record_kind"] = "CALL"
        self.mutate_candidate(mutate)
        with self.assertRaises(GATE.GateError):
            self.prepare()

    def test_public_application_buttons_remain_zero(self) -> None:
        result = self.prepare()
        self.assertEqual(result.summary["counts"]["public_application_buttons"], 0)

    def test_verified_current_meity_calls_remain_zero(self) -> None:
        result = self.prepare()
        self.assertEqual(result.summary["counts"]["verified_meity_current_calls"], 0)
        self.assertEqual(result.summary["calls_coverage_status"], "INCOMPLETE")

    def test_unexpected_non_meity_delta_fails(self) -> None:
        def mutate(rows):
            rows[-1]["source"] = "Unrelated Department"
            rows[-1]["ministry"] = "Unrelated Ministry"
        self.mutate_candidate(mutate)
        with self.assertRaises(GATE.GateError):
            self.prepare()

    def test_application_url_on_candidate_fails(self) -> None:
        def mutate(rows):
            rows[-1]["application_url"] = "https://example.invalid/apply"
        self.mutate_candidate(mutate)
        with self.assertRaises(GATE.GateError):
            self.prepare()

    def test_protected_files_unchanged(self) -> None:
        inputs = GATE.discover_inputs(self.root)
        before = GATE.hash_inventory(GATE.protected_files(inputs, self.output), self.root)
        self.prepare()
        after = GATE.hash_inventory(GATE.protected_files(inputs, self.output), self.root)
        self.assertEqual(before, after)

    def test_manifest_hashes_every_generated_artifact(self) -> None:
        self.prepare()
        manifest = GATE.read_json(GATE.output_paths(self.output)["manifest"])
        self.assertGreaterEqual(len(manifest["outputs"]), 10)
        for item in manifest["outputs"]:
            path = self.root / item["path"]
            self.assertTrue(path.exists())
            self.assertEqual(GATE.sha256_file(path), item["sha256"])


if __name__ == "__main__":
    unittest.main()
