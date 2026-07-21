SSIP Scheme Validation Agent v1
===============================

PURPOSE
-------
Reads:
    data/extracted_scheme_records_v1.json
    data/extraction_failures_v1.json

Creates:
    data/validated_scheme_records_v1.json
    data/admin_review_queue_v1.json
    data/rejected_scheme_records_v1.json
    data/validation_audit_v1.json
    data/validation_summary_v1.json

The validator corrects common extraction errors without fabricating missing facts:
- false monetary values caused by section numbers and ordinary counts
- scheme corpus confused with direct beneficiary support
- eligibility thresholds confused with funding limits
- dates misread as telephone numbers
- national schemes mislabelled as state-specific due to addresses/navigation
- website menus and footers stored as benefits/objectives
- generic registration links treated as scheme application links
- scheme status confused with an individual call/application deadline

FILES TO COPY
-------------
1. Copy the complete folder:
       ssip_agents/validator
   to:
       D:\WebSite\DASHBOARD\Code\SSIP\ssip_agents\validator

2. Copy:
       tests/test_validator_selftest_v1.py
       tests/test_scheme_validation_agent_v1.py
   to:
       D:\WebSite\DASHBOARD\Code\SSIP\tests

3. Copy:
       config/validator_config.json
   to:
       D:\WebSite\DASHBOARD\Code\SSIP\config

4. requirements-validator.txt is optional because no additional package is required.

DO NOT overwrite your existing ssip_agents/__init__.py or tests/__init__.py.

RUN
---
Offline self-test:
    python -m tests.test_validator_selftest_v1

Validate all extracted records:
    set SSIP_VALIDATION_AS_OF=2026-07-08
    python -m tests.test_scheme_validation_agent_v1
    set SSIP_VALIDATION_AS_OF=

Optional one-record test:
    set SSIP_VALIDATION_LIMIT=1
    python -m tests.test_scheme_validation_agent_v1
    set SSIP_VALIDATION_LIMIT=

NOTES
-----
- The as-of date controls whether a verified application deadline is open or closed.
- validated_scheme_records_v1.json contains only records approved for database loading.
- admin_review_queue_v1.json contains records requiring admin confirmation or more evidence.
- validation_audit_v1.json contains every normalized record and every field correction.
