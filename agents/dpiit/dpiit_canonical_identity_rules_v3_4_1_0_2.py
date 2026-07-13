from __future__ import annotations


VERSION = "3.4.1.0.2"
MINISTRY = "Ministry of Commerce and Industry"
DEPARTMENT = "Department for Promotion of Industry and Internal Trade (DPIIT)"
AS_OF = "2026-07-12"


IDENTITY_RULES = [
    {
        "canonical_name": "Startup India Seed Fund Scheme",
        "abbreviation": "SISFS", "entity_type": "SCHEME",
        "master_url": "https://seedfund.startupindia.gov.in/",
        "implementing_agency": "Invest India",
        "aliases": ["Startup India Seed Fund", "SISFS"],
        "evidence": "Official permanent scheme portal with DPIIT named as nodal department.",
    },
    {
        "canonical_name": "Scheme for Facilitating Startups Intellectual Property Protection",
        "abbreviation": "SIPP", "entity_type": "SCHEME",
        "master_url": "https://www.dpiit.gov.in/offerings/schemes-and-services/details/sipp-gTM1UDNtQWa",
        "implementing_agency": "Office of the Controller General of Patents, Designs and Trade Marks",
        "aliases": ["Scheme for Facilitating Startups Intellectual Property Protection (SIPP)", "Startup Intellectual Property Protection", "SIPP"],
        "evidence": "DPIIT schemes-and-services master page.",
    },
    {
        "canonical_name": "Credit Guarantee Scheme for Startups",
        "abbreviation": "CGSS", "entity_type": "SCHEME",
        "master_url": "https://www.startupindia.gov.in/content/sih/en/credit-guarantee-scheme-for-startups.html",
        "implementing_agency": "National Credit Guarantee Trustee Company",
        "aliases": ["CGSS"],
        "evidence": "Official Startup India scheme page with NCGTC implementation evidence.",
    },
    {
        "canonical_name": "Startup India Fund of Funds 2.0",
        "abbreviation": "Startup India FoF 2.0", "entity_type": "SCHEME",
        "master_url": "https://www.startupindia.gov.in/content/dam/startupindia/Startup-India-Fund-of-Funds-2.0-Scheme.pdf",
        "implementing_agency": "SIDBI",
        "aliases": ["Startup India Fund of Funds 2.0 Scheme", "Startup India FoF 2.0"],
        "evidence": "Official 13 April 2026 scheme notification; predecessor/version lineage is not inferred.",
        "lineage_review": True,
    },
    {
        "canonical_name": "Startup India Initiative",
        "abbreviation": "Startup India", "entity_type": "UMBRELLA_PROGRAMME",
        "master_url": "https://www.dpiit.gov.in/offerings/schemes-and-services/details/startup-india-initiative-MTMzYDNtQWa",
        "implementing_agency": "",
        "aliases": ["Startup India Initiative and Related Schemes"],
        "evidence": "DPIIT permanent initiative master page.",
    },
    {
        "canonical_name": "National Startup Awards",
        "abbreviation": "NSA", "entity_type": "UMBRELLA_PROGRAMME",
        "master_url": "https://www.startupindia.gov.in/content/sih/en/nsa-landing.html",
        "implementing_agency": "Invest India",
        "aliases": ["NSA"],
        "evidence": "Permanent awards landing page; numbered editions remain children.",
    },
    {
        "canonical_name": "Bharat Startup Grand Challenge",
        "abbreviation": "BSGC", "entity_type": "UMBRELLA_PROGRAMME",
        "master_url": "https://www.startupindia.gov.in/content/sih/en/bharat-startup-grand-challenge.html",
        "implementing_agency": "Invest India",
        "aliases": ["BSGC"],
        "evidence": "Permanent challenge programme page; individual challenges remain children.",
    },
    {
        "canonical_name": "Bharat Startup Knowledge Access Registry",
        "abbreviation": "BHASKAR", "entity_type": "ECOSYSTEM_PLATFORM",
        "master_url": "https://www.startupindia.gov.in/bhaskar/about",
        "implementing_agency": "Invest India",
        "aliases": ["BHASKAR", "BHASKAR – Bharat Startup Knowledge Access Registry"],
        "evidence": "Official BHASKAR about page.",
    },
    {
        "canonical_name": "MAARG Startup India National Mentorship Platform",
        "abbreviation": "MAARG", "entity_type": "ECOSYSTEM_PLATFORM",
        "master_url": "https://maarg.startupindia.gov.in/",
        "implementing_agency": "Invest India",
        "aliases": ["MAARG", "MAARG – Startup India National Mentorship Platform"],
        "evidence": "Official MAARG platform page.",
    },
    {
        "canonical_name": "Startup India Investor Connect",
        "abbreviation": "", "entity_type": "ECOSYSTEM_PLATFORM",
        "master_url": "https://investorconnect.startupindia.gov.in/",
        "implementing_agency": "Invest India",
        "aliases": [],
        "evidence": "Official Startup India Investor Connect platform.",
    },
    {
        "canonical_name": "DPIIT Startup Recognition",
        "abbreviation": "", "entity_type": "GOVERNMENT_SERVICE",
        "master_url": "https://www.nsws.gov.in/portal/scheme/dpiit-startup-recognition",
        "implementing_agency": "National Single Window System",
        "aliases": ["Apply for DPIIT Startup Recognition"],
        "evidence": "Official NSWS application service; the combined recognition/tax-exemption page remains relationship review.",
        "mixed_service_review_url": "https://www.startupindia.gov.in/content/sih/en/startupgov/startup_recognition_page.html",
    },
]


CHILD_RELATIONSHIP_TYPES = {
    "APPLICATION_CALL": "HAS_APPLICATION_CALL",
    "APPLICATION_PORTAL": "HAS_APPLICATION_PORTAL",
    "AWARD_EDITION": "HAS_AWARD_EDITION",
    "CHALLENGE_INSTANCE": "HAS_CHALLENGE_INSTANCE",
    "GUIDELINE": "HAS_SUPPORTING_GUIDELINE",
    "FAQ": "HAS_FAQ",
    "RESULTS_PAGE": "HAS_RESULTS_PAGE",
}
