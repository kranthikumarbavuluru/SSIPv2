from __future__ import annotations

MINISTRY = "Ministry of Science and Technology"
DEPARTMENT = "Department of Biotechnology"
BIRAC = "Biotechnology Industry Research Assistance Council (BIRAC)"


def build_source_registry() -> list[dict[str, str]]:
    """Return the deterministic, bounded registry of official pilot seeds."""
    sources = [
        ("birac_home", "BIRAC", "https://birac.nic.in/", "ORGANISATION_HOME", "WEEKLY"),
        ("birac_calls", "BIRAC", "https://birac.nic.in/cfp.php", "CALL_DIRECTORY", "WEEKLY"),
        ("dbt_calls", "DBT", "https://dbtindia.gov.in/whats-new/call-for-proposals", "CALL_DIRECTORY", "WEEKLY"),
        ("dbt_call_archive", "DBT", "https://dbtindia.gov.in/whats-new/call-for-proposals/archive", "HISTORICAL_ARCHIVE", "MONTHLY"),
        ("big", "BIRAC", "https://birac.nic.in/big.php", "PROGRAMME", "MONTHLY"),
        ("sbiri", "BIRAC", "https://birac.nic.in/desc_new.php?id=217", "PROGRAMME", "MONTHLY"),
        ("bipp", "BIRAC", "https://birac.nic.in/desc_new.php?id=216", "PROGRAMME", "MONTHLY"),
        ("pace", "BIRAC", "https://birac.nic.in/desc_new.php?id=286", "PROGRAMME", "MONTHLY"),
        ("i4", "BIRAC", "https://birac.nic.in/birac_i4.php", "UMBRELLA_PROGRAMME", "MONTHLY"),
        ("bionest", "BIRAC", "https://birac.nic.in/bionest.php", "PROGRAMME", "MONTHLY"),
        ("seed", "BIRAC", "https://birac.nic.in/seedFundNew.php", "PROGRAMME", "MONTHLY"),
        ("leap", "BIRAC", "https://birac.nic.in/leapFund.php", "PROGRAMME", "MONTHLY"),
        ("ace", "BIRAC", "https://birac.nic.in/aceFundNew.php", "PROGRAMME", "MONTHLY"),
        ("sparsh", "BIRAC", "https://birac.nic.in/desc_new.php?id=58", "PROGRAMME", "MONTHLY"),
        ("eyuva", "BIRAC", "https://birac.nic.in/e_yuva.php", "PROGRAMME", "MONTHLY"),
        ("gci_2026", "BIRAC", "https://birac.nic.in/cfp_view.php?id=118&scheme_type=6", "CHALLENGE", "WEEKLY"),
        ("bioai_2026", "BIRAC", "https://birac.nic.in/cfp_view.php?id=114&scheme_type=46", "APPLICATION_CALL", "WEEKLY"),
        ("pcp_2026", "BIRAC", "https://birac.nic.in/cfp_view.php?id=117&scheme_type=29", "APPLICATION_CALL", "WEEKLY"),
        ("nghm_2025", "BIRAC", "https://birac.nic.in/cfp_view.php?id=116&scheme_type=52", "APPLICATION_CALL", "MONTHLY"),
        ("big_25", "BIRAC", "https://birac.nic.in/cfp.php/portal/desc_new.php?id=443", "HISTORICAL_CALL", "MONTHLY"),
        ("big_24", "BIRAC", "https://birac.nic.in/cfp_view.php?id=31&scheme_type=5", "HISTORICAL_CALL", "MONTHLY"),
        ("bionest_2024", "BIRAC", "https://birac.nic.in/desc_new.php?id=1120", "HISTORICAL_CALL", "QUARTERLY"),
        ("eyuva_centres_2023", "BIRAC", "https://birac.nic.in/cfp_view.php?id=82&scheme_type=31", "HISTORICAL_CALL", "QUARTERLY"),
        ("sparsh_centres_2023", "BIRAC", "https://birac.nic.in/cfp_view.php?id=84&scheme_type=4", "HISTORICAL_CALL", "QUARTERLY"),
        ("biocare", "DBT", "https://dbtindia.gov.in/biotechnology-career-advancement-and-re-orientation-biocare-programmes", "PROGRAMME", "MONTHLY"),
        ("dbt_pg", "DBT", "https://pgt.dbtindia.gov.in/", "PROGRAMME", "MONTHLY"),
        ("big_guide", "BIRAC", "https://birac.nic.in/webcontent/big_user_guide.pdf", "SUPPORTING_DOCUMENT", "QUARTERLY"),
        ("pace_guide", "BIRAC", "https://birac.nic.in/webcontent/1745298188_PACE_scheme_guidelines_16_04_2025.pdf", "SUPPORTING_DOCUMENT", "QUARTERLY"),
        ("biocare_guide", "DBT", "https://dbtindia.gov.in/sites/default/files/BioCARe%20Guidelines%202024_0.pdf", "SUPPORTING_DOCUMENT", "QUARTERLY"),
        ("sparsh_guide", "BIRAC", "https://birac.nic.in/webcontent/Sparsh_Guidelines_Ver_3.pdf", "SUPPORTING_DOCUMENT", "QUARTERLY"),
    ]
    return [
        {
            "source_id": source_id,
            "source_owner": owner,
            "official_url": url,
            "authoritative_role": role,
            "permitted_domain": url.split("/")[2].casefold(),
            "monitoring_frequency": frequency,
            "crawl_scope": "REGISTERED_SEED_AND_BOUNDED_OFFICIAL_LINKS",
            "pagination_rule": "NO_AUTOINCREMENT_MAX_DEPTH_1",
            "rate_limit_seconds": "0.50",
            "canonical_rule": "HTTPS_LOWERCASE_HOST_DROP_TRACKING_AND_FRAGMENT",
            "ownership_rule": "REQUIRE_RECORD_LEVEL_DBT_OR_BIRAC_EVIDENCE",
            "exclusion_rule": "DIRECTORY_OR_DOCUMENT_IS_NOT_A_CATALOGUE_IDENTITY",
        }
        for source_id, owner, url, role, frequency in sources
    ]
