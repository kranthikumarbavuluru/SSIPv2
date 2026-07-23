from __future__ import annotations


VERSION = "3.4.1.0.3"
AS_OF = "2026-07-12"
MINISTRY = "Ministry of Commerce and Industry"
DEPARTMENT = "Department for Promotion of Industry and Internal Trade (DPIIT)"

GSR_108_URL = "https://www.dpiit.gov.in/static/uploads/2026/02/119e52e2a36f652215a32c3ccc5f9c66.pdf"
STARTUP_INITIATIVE_URL = "https://www.dpiit.gov.in/offerings/schemes-and-services/details/startup-india-initiative-MTMzYDNtQWa"
RECOGNITION_PAGE_URL = "https://www.startupindia.gov.in/content/sih/en/startupgov/startup_recognition_page.html"
RECOGNITION_APPLICATION_URL = "https://www.nsws.gov.in/portal/scheme/dpiit-startup-recognition"
IAC_FORM_URL = "https://www.startupindia.gov.in/content/sih/en/form80iac.html"
IMB_URL = "https://www.startupindia.gov.in/content/sih/en/startupgov/imb.html"
FOF2_URL = "https://www.startupindia.gov.in/content/dam/startupindia/Startup-India-Fund-of-Funds-2.0-Scheme.pdf"

OWNERSHIP_RULES = {
    "dpiit_candidate_ec1a28c95caa67afc540": {
        "decision": "VERIFIED_DPIIT_ISSUED_NOTIFICATION",
        "ownership_status": "VERIFIED_DPIIT_ISSUER",
        "owning_department": DEPARTMENT,
        "content_authority": DEPARTMENT,
        "entity_boundary": "SUPPORTING_LEGAL_NOTIFICATION",
        "final_page_role": "NOTIFICATION",
        "evidence_url": GSR_108_URL,
        "evidence_basis": "The official Gazette text identifies the Ministry of Commerce and Industry, DPIIT, and governs startup recognition and 80-IAC certification.",
        "confidence": "1.00",
    },
    "dpiit_candidate_922d99e5fcaccfec5f80": {
        "decision": "VERIFIED_DPIIT_PLATFORM_DIRECTORY_CONTEXT",
        "ownership_status": "VERIFIED_PLATFORM_CONTEXT",
        "owning_department": DEPARTMENT,
        "content_authority": "Startup India platform under the DPIIT initiative",
        "entity_boundary": "CROSS_DEPARTMENT_SCHEME_DIRECTORY",
        "final_page_role": "SOURCE_DIRECTORY",
        "evidence_url": STARTUP_INITIATIVE_URL,
        "evidence_basis": "DPIIT coordinates Startup India, but the directory explicitly contains schemes from multiple ministries and departments; child ownership remains candidate-specific.",
        "confidence": "0.96",
    },
    "dpiit_candidate_99c433408283d26eddd7": {
        "decision": "VERIFIED_DPIIT_PLATFORM_DIRECTORY_CONTEXT",
        "ownership_status": "VERIFIED_PLATFORM_CONTEXT",
        "owning_department": DEPARTMENT,
        "content_authority": "Startup India platform under the DPIIT initiative",
        "entity_boundary": "MULTI_OWNER_PROGRAMME_AND_CHALLENGE_DIRECTORY",
        "final_page_role": "SOURCE_DIRECTORY",
        "evidence_url": STARTUP_INITIATIVE_URL,
        "evidence_basis": "The listing is a Startup India platform directory. Hosting establishes directory context only; every listed programme or challenge requires separate issuer evidence.",
        "confidence": "0.96",
    },
    "dpiit_candidate_a2f1601863f60d1a6e76": {
        "decision": "RESOLVED_AS_GENERIC_PLATFORM_UTILITY",
        "ownership_status": "NO_ENTITY_OWNERSHIP_ASSIGNED",
        "owning_department": "",
        "content_authority": "Startup India platform host",
        "entity_boundary": "GENERIC_ARCHIVE_UTILITY",
        "final_page_role": "ARCHIVED_PAGE",
        "evidence_url": "https://www.startupindia.gov.in/content/sih/en/archive-notice.html",
        "evidence_basis": "The page is a generic archive notice and contains no surviving issuer or programme identity; portal hosting is not used to infer ownership.",
        "confidence": "1.00",
    },
}

SERVICE_BOUNDARY_RULE = {
    "review_candidate_id": "dpiit_candidate_9f03f2aa5eec0f36b7f2",
    "recognition_master_id": "dpiit_master_6c1afb477ef37cd6acaa",
    "recognition_name": "DPIIT Startup Recognition",
    "tax_service_name": "Section 80-IAC Tax Exemption Eligibility Certification for Startups",
    "tax_service_url": IAC_FORM_URL,
    "tax_service_authority": "Inter-Ministerial Board of Certification",
    "tax_service_owner": DEPARTMENT,
    "decision": "SPLIT_INTO_SEPARATE_GOVERNMENT_SERVICES",
    "relationship_type": "REQUIRES_DPIIT_RECOGNITION",
    "evidence_urls": [GSR_108_URL, RECOGNITION_PAGE_URL, IAC_FORM_URL, IMB_URL],
    "evidence_basis": "Official sources define recognition and 80-IAC eligibility certification as separate applications and decisions; recognition is a prerequisite for the tax service.",
}

LINEAGE_RULE = {
    "review_candidate_id": "dpiit_candidate_ec3486a7fcbcb33c0ea0",
    "current_master_id": "dpiit_master_c89f3d410e746f1594dc",
    "current_name": "Startup India Fund of Funds 2.0",
    "predecessor_name": "Fund of Funds for Startups 1.0",
    "relationship_type": "VERSION_LINEAGE_FROM",
    "decision": "SEPARATE_VERSION_IDENTITY_CONFIRMED",
    "merge_allowed": "0",
    "evidence_url": FOF2_URL,
    "evidence_basis": "The official notification names Fund of Funds 2.0 and references the earlier 1.0 structure. This supports lineage, not identity merging.",
}

EVIDENCE_RECORDS = [
    ("GSR_108_2026", GSR_108_URL, "DPIIT is the issuing department; the notification separately specifies startup recognition and 80-IAC certification."),
    ("STARTUP_INDIA_INITIATIVE", STARTUP_INITIATIVE_URL, "DPIIT coordinates implementation of the Startup India initiative."),
    ("GOVERNMENT_SCHEME_DIRECTORY", "https://www.startupindia.gov.in/content/sih/en/government-schemes.html", "The directory states that it covers initiatives from multiple Central ministries and departments."),
    ("PROGRAMME_DIRECTORY", "https://www.startupindia.gov.in/content/sih/en/ams-application/application-listing.html", "The Startup India listing contains programmes and challenges whose issuer must be checked individually."),
    ("ARCHIVE_UTILITY", "https://www.startupindia.gov.in/content/sih/en/archive-notice.html", "Generic archived-page notice without a surviving programme identity."),
    ("RECOGNITION_AND_TAX_PAGE", RECOGNITION_PAGE_URL, "The page presents DPIIT recognition first and a separate post-recognition 80-IAC application."),
    ("RECOGNITION_APPLICATION", RECOGNITION_APPLICATION_URL, "NSWS hosts the Registration as a Startup application for DPIIT recognition."),
    ("IAC_APPLICATION", IAC_FORM_URL, "A distinct form collects information for Section 80-IAC eligibility certification."),
    ("IMB_AUTHORITY", IMB_URL, "The Inter-Ministerial Board, convened by DPIIT, validates startups for the 80-IAC tax benefit."),
    ("FOF2_NOTIFICATION", FOF2_URL, "The notification establishes Startup India Fund of Funds 2.0 and references the earlier 1.0 structure."),
]
