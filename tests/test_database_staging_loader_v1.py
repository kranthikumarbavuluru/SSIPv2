from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from database.staging_loader_v1 import default_paths, load_to_staging


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    paths = default_paths(project_root)
    summary = load_to_staging(paths)

    print("\n" + "=" * 92)
    print("DATABASE STAGING LOAD COMPLETED")
    print("=" * 92)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    with sqlite3.connect(paths.database_path) as connection:
        approved = connection.execute(
            """
            SELECT scheme_name, source, application_status, validation_score,
                   funding_maximum, scheme_corpus
            FROM scheme_staging
            ORDER BY source, scheme_name
            """
        ).fetchall()
        reviews = connection.execute(
            """
            SELECT scheme_name, source, decision, priority, validation_score
            FROM admin_review_queue
            WHERE review_status = 'PENDING'
            ORDER BY CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                     validation_score DESC
            """
        ).fetchall()

    print("\n" + "=" * 92)
    print("STAGED APPROVED SCHEMES")
    print("=" * 92)
    for name, source, application_status, score, funding_max, corpus in approved:
        print(
            f"[{score:.3f}] {source:<14} | {name}\n"
            f"    Application: {application_status} | Funding max: {funding_max} | Corpus: {corpus}"
        )

    print("\n" + "=" * 92)
    print("PENDING ADMIN REVIEW")
    print("=" * 92)
    for name, source, decision, priority, score in reviews:
        print(f"[{priority:<6}] [{score:.3f}] {source:<14} | {name} | {decision}")

    print("\nFiles created/updated:")
    print(paths.database_path)
    print(paths.summary_path)


if __name__ == "__main__":
    main()
