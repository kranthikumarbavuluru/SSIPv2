from __future__ import annotations

import json
from pathlib import Path

from ssip_agents.classifier.meity_classification_hotfix_v2_2 import run_hotfix


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = run_hotfix(project_root)

    assert result["meity_classified_record_count"] == 6
    assert result["meity_master_count_after"] == 6
    assert result["master_candidate_count_after"] == 34

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nMeitY Classification Hotfix integration test passed.")
    print("Master candidates:", result["master_candidate_count_after"])
    print("MeitY masters:", result["meity_master_count_after"])


if __name__ == "__main__":
    main()
