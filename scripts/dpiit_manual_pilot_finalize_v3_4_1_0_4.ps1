[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$version = "3.4.1.0.4"
$versionPath = "v3_4_1_0_4"
$phaseDate = "2026-07-12"

$outputDir = Join-Path `
  $root `
  "data\departments\dpiit\$versionPath"

$auditDir = Join-Path $root "data\audit"

$pilotPath = Join-Path `
  $outputDir `
  "dpiit_extraction_pilot_records_v3_4_1_0_4.csv"

$evidencePath = Join-Path `
  $outputDir `
  "dpiit_field_evidence_registry_v3_4_1_0_4.csv"

$reviewPath = Join-Path `
  $outputDir `
  "dpiit_extraction_review_queue_v3_4_1_0_4.csv"

$lookupPath = Join-Path `
  $outputDir `
  "dpiit_pilot_identity_lookup_v3_4_1_0_4.csv"

$validationPath = Join-Path `
  $outputDir `
  "dpiit_extraction_validation_v3_4_1_0_4.json"

$summaryPath = Join-Path `
  $outputDir `
  "dpiit_extraction_summary_v3_4_1_0_4.json"

$manifestPath = Join-Path `
  $outputDir `
  "dpiit_extraction_manifest_v3_4_1_0_4.json"

$prechangeAuditPath = Join-Path `
  $auditDir `
  "dpiit_v3_4_1_0_4_manual_prechange_sha256.json"

$postchangeAuditPath = Join-Path `
  $auditDir `
  "dpiit_v3_4_1_0_4_manual_postchange_sha256.json"

foreach ($requiredPath in @(
    $pilotPath,
    $evidencePath,
    $reviewPath,
    $lookupPath,
    $prechangeAuditPath
)) {
    if (-not (Test-Path $requiredPath)) {
        throw "Required phase input is missing: $requiredPath"
    }
}

function Get-FileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return "MISSING"
    }

    return (
        Get-FileHash `
          -Path $Path `
          -Algorithm SHA256
    ).Hash.ToLower()
}

function Get-SSIPTreeHash {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return "MISSING"
    }

    $resolvedRoot = (Resolve-Path $Path).Path

    $hashLines = @(
        Get-ChildItem `
          -Path $resolvedRoot `
          -Recurse `
          -File |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = $_.FullName.Substring(
                $resolvedRoot.Length
            ).TrimStart("\")

            $fileHash = (
                Get-FileHash `
                  -Path $_.FullName `
                  -Algorithm SHA256
            ).Hash.ToLower()

            "$relativePath`t$fileHash"
        }
    )

    $temporaryFile = [System.IO.Path]::GetTempFileName()

    try {
        [System.IO.File]::WriteAllLines(
            $temporaryFile,
            $hashLines,
            [System.Text.UTF8Encoding]::new($false)
        )

        return (
            Get-FileHash `
              -Path $temporaryFile `
              -Algorithm SHA256
        ).Hash.ToLower()
    }
    finally {
        Remove-Item `
          -Path $temporaryFile `
          -Force `
          -ErrorAction SilentlyContinue
    }
}

function Write-DeterministicJson {
    param(
        [Parameter(Mandatory = $true)]
        $Object,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $json = $Object |
      ConvertTo-Json -Depth 30

    [System.IO.File]::WriteAllText(
        $Path,
        $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Test-OfficialEvidenceUrl {
    param(
        [string]$Url
    )

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $false
    }

    try {
        $uri = [System.Uri]$Url

        if ($uri.Scheme -ne "https") {
            return $false
        }

        $hostName = $uri.DnsSafeHost.ToLower()

        $officialDomains = @(
            "dpiit.gov.in",
            "startupindia.gov.in",
            "nsws.gov.in",
            "sidbi.in"
        )

        foreach ($domain in $officialDomains) {
            if (
                $hostName -eq $domain -or
                $hostName.EndsWith("." + $domain)
            ) {
                return $true
            }
        }
    }
    catch {
        return $false
    }

    return $false
}

$baseline = Get-Content `
  -Path $prechangeAuditPath `
  -Raw |
ConvertFrom-Json

$pilotRecords = @(Import-Csv $pilotPath)
$evidenceRows = @(Import-Csv $evidencePath)
$reviewRows = @(Import-Csv $reviewPath)

$expectedMasterIds = @(
    "dpiit_master_6c1afb477ef37cd6acaa",
    "dpiit_master_3b767c3b91080149015f",
    "dpiit_master_c89f3d410e746f1594dc"
)

$actualMasterIds = @(
    $pilotRecords.master_id |
    Sort-Object -Unique
)

$expectedSorted = @(
    $expectedMasterIds |
    Sort-Object
)

$exactMasterIdsPreserved = (
    ($actualMasterIds -join "|") -eq
    ($expectedSorted -join "|")
)

$duplicateMasterIds = @(
    $pilotRecords |
    Group-Object master_id |
    Where-Object {
        $_.Count -gt 1
    }
)

$duplicateEvidenceIds = @(
    $evidenceRows |
    Group-Object evidence_id |
    Where-Object {
        $_.Count -gt 1
    }
)

$duplicateReviewIds = @(
    $reviewRows |
    Group-Object review_id |
    Where-Object {
        $_.Count -gt 1
    }
)

$evidenceRequiredFields = @(
    "canonical_name",
    "official_abbreviation",
    "record_kind",
    "owning_ministry",
    "owning_department",
    "implementing_agency",
    "platform_host",
    "programme_status",
    "objective",
    "eligibility",
    "beneficiary_type",
    "startup_stage",
    "benefits",
    "funding_minimum",
    "funding_maximum",
    "currency",
    "application_process",
    "required_documents",
    "official_page_url",
    "application_url",
    "guideline_url",
    "notification_url",
    "contact_details",
    "identity_evidence_url",
    "ownership_evidence_url",
    "status_evidence_url"
)

$missingEvidence = @()

foreach ($pilotRecord in $pilotRecords) {
    foreach ($fieldName in $evidenceRequiredFields) {
        $fieldValue = [string]$pilotRecord.$fieldName

        if (-not [string]::IsNullOrWhiteSpace($fieldValue)) {
            $matchingEvidence = @(
                $evidenceRows |
                Where-Object {
                    $_.master_id -eq $pilotRecord.master_id -and
                    $_.field_name -eq $fieldName -and
                    $_.extracted_value -eq $fieldValue
                }
            )

            if ($matchingEvidence.Count -lt 1) {
                $missingEvidence += [PSCustomObject][ordered]@{
                    master_id = $pilotRecord.master_id
                    canonical_name = $pilotRecord.canonical_name
                    field_name = $fieldName
                    current_value = $fieldValue
                }
            }
        }
    }
}

$evidenceValueMismatches = @()

foreach ($evidenceRow in $evidenceRows) {
    $pilotRecord = @(
        $pilotRecords |
        Where-Object {
            $_.master_id -eq $evidenceRow.master_id
        }
    )

    if ($pilotRecord.Count -ne 1) {
        $evidenceValueMismatches += [PSCustomObject][ordered]@{
            evidence_id = $evidenceRow.evidence_id
            reason = "MASTER_ID_NOT_FOUND"
            master_id = $evidenceRow.master_id
            field_name = $evidenceRow.field_name
        }

        continue
    }

    $record = $pilotRecord[0]
    $property = $record.PSObject.Properties[$evidenceRow.field_name]

    if ($null -eq $property) {
        $evidenceValueMismatches += [PSCustomObject][ordered]@{
            evidence_id = $evidenceRow.evidence_id
            reason = "FIELD_NOT_FOUND"
            master_id = $evidenceRow.master_id
            field_name = $evidenceRow.field_name
        }

        continue
    }

    if (
        [string]$property.Value -ne
        [string]$evidenceRow.extracted_value
    ) {
        $evidenceValueMismatches += [PSCustomObject][ordered]@{
            evidence_id = $evidenceRow.evidence_id
            reason = "EXTRACTED_VALUE_MISMATCH"
            master_id = $evidenceRow.master_id
            field_name = $evidenceRow.field_name
            record_value = [string]$property.Value
            evidence_value = [string]$evidenceRow.extracted_value
        }
    }
}

$nonOfficialEvidenceUrls = @(
    $evidenceRows |
    Where-Object {
        -not (Test-OfficialEvidenceUrl $_.evidence_url)
    } |
    Select-Object `
      evidence_id,
      master_id,
      field_name,
      evidence_url
)

$allowedStatuses = @(
    "CURRENT_SERVICE_INFORMATION_AVAILABLE",
    "CURRENT_SCHEME_INFORMATION_AVAILABLE",
    "APPLICATION_INFORMATION_AVAILABLE",
    "APPLICATION_STATUS_REQUIRES_VERIFICATION",
    "HISTORICAL_INFORMATION_ONLY",
    "NEEDS_CURRENT_STATUS_VERIFICATION"
)

$invalidStatuses = @(
    $pilotRecords |
    Where-Object {
        $_.programme_status -notin $allowedStatuses
    } |
    Select-Object `
      master_id,
      canonical_name,
      programme_status
)

$allowedReviewDecisions = @(
    "APPROVED_PILOT_RECORD",
    "NEEDS_FIELD_EVIDENCE",
    "NEEDS_STATUS_VERIFICATION",
    "NEEDS_APPLICATION_VERIFICATION",
    "NEEDS_MANUAL_REVIEW"
)

$invalidReviewDecisions = @(
    $pilotRecords |
    Where-Object {
        $_.review_decision -notin $allowedReviewDecisions
    } |
    Select-Object `
      master_id,
      canonical_name,
      review_decision
)

$recognitionId = "dpiit_master_6c1afb477ef37cd6acaa"
$taxServiceId = "dpiit_master_3b767c3b91080149015f"
$fof2Id = "dpiit_master_c89f3d410e746f1594dc"

$recognitionRecord = @(
    $pilotRecords |
    Where-Object {
        $_.master_id -eq $recognitionId
    }
)

$taxServiceRecord = @(
    $pilotRecords |
    Where-Object {
        $_.master_id -eq $taxServiceId
    }
)

$fof2Record = @(
    $pilotRecords |
    Where-Object {
        $_.master_id -eq $fof2Id
    }
)

$relationshipPath = Join-Path `
  $root `
  "data\departments\dpiit\v3_4_1_0_3\dpiit_service_relationship_registry_v3_4_1_0_3.csv"

$lineagePath = Join-Path `
  $root `
  "data\departments\dpiit\v3_4_1_0_3\dpiit_scheme_lineage_decisions_v3_4_1_0_3.csv"

$recognitionRelationship = @(
    Import-Csv $relationshipPath |
    Where-Object {
        $_.source_master_id -eq $taxServiceId -and
        $_.target_master_id -eq $recognitionId -and
        $_.relationship_type -eq "REQUIRES_DPIIT_RECOGNITION" -and
        $_.status -eq "LOCKED_OFFICIAL_SERVICE_RELATIONSHIP"
    }
)

$fofLineage = @(
    Import-Csv $lineagePath |
    Where-Object {
        $_.current_master_id -eq $fof2Id -and
        $_.relationship_type -eq "VERSION_LINEAGE_FROM" -and
        $_.decision -eq "SEPARATE_VERSION_IDENTITY_CONFIRMED" -and
        $_.merge_allowed -eq "0" -and
        $_.publication_status -eq "NOT_PUBLISHED"
    }
)

$frozenFileResults = [ordered]@{}
$allFrozenFilesUnchanged = $true

foreach ($property in $baseline.frozen_files.PSObject.Properties) {
    $relativePath = $property.Name
    $relativeOsPath = $relativePath.Replace(
        "/",
        [System.IO.Path]::DirectorySeparatorChar
    )

    $fullPath = Join-Path $root $relativeOsPath
    $beforeHash = [string]$property.Value
    $afterHash = Get-FileSha256 -Path $fullPath
    $unchanged = ($beforeHash -eq $afterHash)

    if (-not $unchanged) {
        $allFrozenFilesUnchanged = $false
    }

    $frozenFileResults[$relativePath] = [ordered]@{
        before_sha256 = $beforeHash
        after_sha256 = $afterHash
        unchanged = $unchanged
    }
}

$frozenTreeResults = [ordered]@{}
$allFrozenTreesUnchanged = $true

foreach ($property in $baseline.frozen_trees.PSObject.Properties) {
    $relativePath = $property.Name
    $relativeOsPath = $relativePath.Replace(
        "/",
        [System.IO.Path]::DirectorySeparatorChar
    )

    $fullPath = Join-Path $root $relativeOsPath
    $beforeHash = [string]$property.Value
    $afterHash = Get-SSIPTreeHash -Path $fullPath
    $unchanged = ($beforeHash -eq $afterHash)

    if (-not $unchanged) {
        $allFrozenTreesUnchanged = $false
    }

    $frozenTreeResults[$relativePath] = [ordered]@{
        before_sha256 = $beforeHash
        after_sha256 = $afterHash
        unchanged = $unchanged
    }
}

$activeCataloguePath = Join-Path `
  $root `
  "data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv"

$publishedCataloguePath = Join-Path `
  $root `
  "data\publication\20260710T162806+0000_f4936983\catalogue.csv"

$activeCatalogueRows = @(Import-Csv $activeCataloguePath)
$publishedCatalogueRows = @(Import-Csv $publishedCataloguePath)

$publishedPilotIds = @()

foreach ($expectedId in $expectedMasterIds) {
    foreach ($catalogueRow in $activeCatalogueRows) {
        if (
            @($catalogueRow.PSObject.Properties.Value) -contains
            $expectedId
        ) {
            $publishedPilotIds += $expectedId
            break
        }
    }
}

$dashboardVisibleOutput = & python -c "from pathlib import Path; from agents.governed_v1.common import dashboard_public_ids; root=Path('.').resolve(); active=root/'data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv'; print(len(dashboard_public_ids(root, active)))"

$dashboardVisibleCount = [int](
    $dashboardVisibleOutput |
    Select-Object -Last 1
)

$canonicalPublicationHashOutput = & python -c "from pathlib import Path; from agents.publication_agent import content_hash; p=Path(r'data\publication\20260710T162806+0000_f4936983\catalogue.csv'); print(content_hash(p.read_bytes()))"

$canonicalPublicationHash = [string](
    $canonicalPublicationHashOutput |
    Select-Object -Last 1
)

$noCallRecords = @(
    $pilotRecords |
    Where-Object {
        $_.record_kind -match "CALL|ROUND|COHORT"
    }
).Count -eq 0

$noOpenApplicationStatus = @(
    $pilotRecords |
    Where-Object {
        $_.programme_status -match "OPEN_FOR_APPLICATIONS"
    }
).Count -eq 0

$fofDirectApplicationRulePreserved = (
    $fof2Record.Count -eq 1 -and
    $fof2Record[0].eligibility -match
      "Alternative Investment Funds" -and
    $fof2Record[0].application_process -match
      "startups do not apply directly"
)

$checks = [ordered]@{
    exactly_three_pilot_records = (
        $pilotRecords.Count -eq 3
    )

    exact_master_ids_preserved = (
        $exactMasterIdsPreserved
    )

    no_duplicate_master_ids = (
        $duplicateMasterIds.Count -eq 0
    )

    exactly_59_evidence_rows = (
        $evidenceRows.Count -eq 59
    )

    exactly_11_review_rows = (
        $reviewRows.Count -eq 11
    )

    no_duplicate_evidence_ids = (
        $duplicateEvidenceIds.Count -eq 0
    )

    no_duplicate_review_ids = (
        $duplicateReviewIds.Count -eq 0
    )

    every_populated_public_field_has_evidence = (
        $missingEvidence.Count -eq 0
    )

    evidence_values_match_pilot_records = (
        $evidenceValueMismatches.Count -eq 0
    )

    all_evidence_urls_are_official_https = (
        $nonOfficialEvidenceUrls.Count -eq 0
    )

    all_programme_statuses_are_allowed = (
        $invalidStatuses.Count -eq 0
    )

    all_review_decisions_are_allowed = (
        $invalidReviewDecisions.Count -eq 0
    )

    recognition_and_80iac_are_separate = (
        $recognitionRecord.Count -eq 1 -and
        $taxServiceRecord.Count -eq 1 -and
        $recognitionId -ne $taxServiceId
    )

    requires_dpiit_recognition_relationship_preserved = (
        $recognitionRelationship.Count -eq 1
    )

    fof2_identity_is_separate = (
        $fof2Record.Count -eq 1
    )

    fof2_version_lineage_is_preserved = (
        $fofLineage.Count -eq 1
    )

    fof2_is_not_direct_startup_application = (
        $fofDirectApplicationRulePreserved
    )

    no_call_or_round_stored_as_permanent_record = (
        $noCallRecords
    )

    no_unsupported_open_application_status = (
        $noOpenApplicationStatus
    )

    no_pilot_record_is_in_active_catalogue = (
        $publishedPilotIds.Count -eq 0
    )

    active_catalogue_row_count_is_137 = (
        $activeCatalogueRows.Count -eq 137
    )

    immutable_publication_row_count_is_137 = (
        $publishedCatalogueRows.Count -eq 137
    )

    dashboard_visible_record_count_is_51 = (
        $dashboardVisibleCount -eq 51
    )

    canonical_publication_hash_is_preserved = (
        $canonicalPublicationHash -eq
        "838ca86cde4b2ceebd4325850c783823c931a3e42ef5c4ef74b7ae54a4596e4d"
    )

    all_frozen_files_are_unchanged = (
        $allFrozenFilesUnchanged
    )

    all_frozen_trees_are_unchanged = (
        $allFrozenTreesUnchanged
    )

    no_publication_occurred = (
        $publishedPilotIds.Count -eq 0 -and
        $allFrozenFilesUnchanged
    )
}

$failedChecks = @(
    $checks.GetEnumerator() |
    Where-Object {
        -not [bool]$_.Value
    } |
    ForEach-Object {
        $_.Key
    }
)

$overallStatus = if ($failedChecks.Count -eq 0) {
    "PASS"
}
else {
    "FAIL"
}

$recordSummaries = @(
    foreach ($pilotRecord in (
        $pilotRecords |
        Sort-Object master_id
    )) {
        $recordEvidence = @(
            $evidenceRows |
            Where-Object {
                $_.master_id -eq $pilotRecord.master_id
            }
        )

        $recordReviews = @(
            $reviewRows |
            Where-Object {
                $_.master_id -eq $pilotRecord.master_id
            }
        )

        [PSCustomObject][ordered]@{
            master_id = $pilotRecord.master_id
            canonical_name = $pilotRecord.canonical_name
            record_kind = $pilotRecord.record_kind
            programme_status = $pilotRecord.programme_status
            field_completeness = $pilotRecord.field_completeness
            confidence = $pilotRecord.confidence
            review_decision = $pilotRecord.review_decision
            evidence_count = $recordEvidence.Count
            open_review_count = $recordReviews.Count
            open_review_fields = @(
                $recordReviews.field_name |
                Sort-Object
            )
        }
    }
)

$applicationStatusConclusions = @(
    [PSCustomObject][ordered]@{
        master_id = $recognitionId
        conclusion = "Current service information and an NSWS application route are available. This is a continuing government service, not a time-bound call."
    }

    [PSCustomObject][ordered]@{
        master_id = $taxServiceId
        conclusion = "Application information is available for the separate 80-IAC eligibility-certification service. DPIIT Startup Recognition remains a prerequisite."
    }

    [PSCustomObject][ordered]@{
        master_id = $fof2Id
        conclusion = "Application information is available for eligible SEBI-registered AIFs through SIDBI. Startups do not apply directly to DPIIT for FoF 2.0 capital."
    }
)

$validation = [ordered]@{
    version = $version
    phase = "DPIIT Governed Field Extraction and Evidence Validation Pilot"
    execution_mode = "MANUAL_PREVIEW_ONLY"
    as_of_date = $phaseDate
    baseline_recorded_at = $baseline.recorded_at
    overall_status = $overallStatus
    failed_checks = $failedChecks

    counts = [ordered]@{
        pilot_records = $pilotRecords.Count
        evidence_rows = $evidenceRows.Count
        review_rows = $reviewRows.Count
        active_catalogue_rows = $activeCatalogueRows.Count
        immutable_publication_rows = $publishedCatalogueRows.Count
        dashboard_visible_records = $dashboardVisibleCount
    }

    checks = $checks

    validation_findings = [ordered]@{
        missing_evidence = $missingEvidence
        evidence_value_mismatches = $evidenceValueMismatches
        non_official_evidence_urls = $nonOfficialEvidenceUrls
        invalid_programme_statuses = $invalidStatuses
        invalid_review_decisions = $invalidReviewDecisions
        duplicate_master_ids = @(
            $duplicateMasterIds.Name
        )
        duplicate_evidence_ids = @(
            $duplicateEvidenceIds.Name
        )
        duplicate_review_ids = @(
            $duplicateReviewIds.Name
        )
        pilot_ids_found_in_active_catalogue = $publishedPilotIds
    }

    preservation = [ordered]@{
        frozen_files = $frozenFileResults
        frozen_trees = $frozenTreeResults
        canonical_publication_content_hash = $canonicalPublicationHash
    }

    relationships = [ordered]@{
        requires_dpiit_recognition = (
            $recognitionRelationship |
            Select-Object `
              relationship_id,
              source_master_id,
              target_master_id,
              relationship_type,
              status
        )

        fof2_version_lineage = (
            $fofLineage |
            Select-Object `
              decision_id,
              current_master_id,
              current_name,
              predecessor_name,
              relationship_type,
              decision,
              merge_allowed,
              publication_status
        )
    }
}

Write-DeterministicJson `
  -Object $validation `
  -Path $validationPath

$summary = [ordered]@{
    version = $version
    phase = "DPIIT Governed Field Extraction and Evidence Validation Pilot"
    execution_mode = "MANUAL_PREVIEW_ONLY"
    as_of_date = $phaseDate
    overall_status = $overallStatus

    scope = [ordered]@{
        exact_record_count = 3
        discovery_performed = $false
        new_identity_created = $false
        calls_or_rounds_extracted = $false
        database_modified = $false
        dashboard_modified = $false
        publication_performed = $false
    }

    record_summaries = $recordSummaries
    application_status_conclusions = $applicationStatusConclusions

    totals = [ordered]@{
        pilot_records = $pilotRecords.Count
        evidence_rows = $evidenceRows.Count
        open_review_rows = $reviewRows.Count
        failed_validation_checks = $failedChecks.Count
    }

    files_created_or_updated_in_phase = @(
        "data/departments/dpiit/v3_4_1_0_4/dpiit_pilot_identity_lookup_v3_4_1_0_4.csv",
        "data/departments/dpiit/v3_4_1_0_4/dpiit_extraction_pilot_records_v3_4_1_0_4.csv",
        "data/departments/dpiit/v3_4_1_0_4/dpiit_field_evidence_registry_v3_4_1_0_4.csv",
        "data/departments/dpiit/v3_4_1_0_4/dpiit_extraction_review_queue_v3_4_1_0_4.csv",
        "data/departments/dpiit/v3_4_1_0_4/dpiit_extraction_validation_v3_4_1_0_4.json",
        "data/departments/dpiit/v3_4_1_0_4/dpiit_extraction_summary_v3_4_1_0_4.json",
        "data/departments/dpiit/v3_4_1_0_4/dpiit_extraction_manifest_v3_4_1_0_4.json",
        "data/audit/dpiit_v3_4_1_0_4_manual_prechange_sha256.json",
        "data/audit/dpiit_v3_4_1_0_4_manual_postchange_sha256.json",
        "scripts/dpiit_manual_pilot_finalize_v3_4_1_0_4.ps1"
    )

    pre_existing_governed_files_modified = @()

    governance_conclusions = @(
        "DPIIT Startup Recognition remains a government service.",
        "Section 80-IAC remains a separate government service requiring DPIIT Startup Recognition.",
        "Startup India Fund of Funds 2.0 remains a separate scheme identity.",
        "Fund of Funds 2.0 remains linked to Fund of Funds for Startups 1.0 through VERSION_LINEAGE_FROM without merging.",
        "The INR 10,000 crore FoF 2.0 corpus is not stored as a universal startup-level funding maximum.",
        "No record was published."
    )
}

Write-DeterministicJson `
  -Object $summary `
  -Path $summaryPath

$manifestInputPaths = @(
    $pilotPath,
    $evidencePath,
    $reviewPath,
    $lookupPath,
    $validationPath,
    $summaryPath
)

$manifestFiles = @(
    foreach ($filePath in $manifestInputPaths) {
        $item = Get-Item $filePath

        [PSCustomObject][ordered]@{
            relative_path = $item.FullName.Substring(
                $root.Length
            ).TrimStart("\").Replace("\", "/")

            sha256 = Get-FileSha256 -Path $item.FullName
            size_bytes = $item.Length
        }
    }
)

$manifest = [ordered]@{
    manifest_version = "1.0"
    phase_version = $version
    phase = "DPIIT Governed Field Extraction and Evidence Validation Pilot"
    execution_mode = "MANUAL_PREVIEW_ONLY"
    generated_from_baseline_at = $baseline.recorded_at
    output_directory = "data/departments/dpiit/v3_4_1_0_4"
    validation_status = $overallStatus
    pilot_record_count = $pilotRecords.Count
    evidence_row_count = $evidenceRows.Count
    review_row_count = $reviewRows.Count
    files = $manifestFiles

    publication = [ordered]@{
        permitted = $false
        performed = $false
        active_catalogue_modified = $false
        immutable_publication_modified = $false
    }
}

Write-DeterministicJson `
  -Object $manifest `
  -Path $manifestPath

$outputAuditPaths = @(
    $pilotPath,
    $evidencePath,
    $reviewPath,
    $lookupPath,
    $validationPath,
    $summaryPath,
    $manifestPath
)

$outputAuditHashes = [ordered]@{}

foreach ($filePath in $outputAuditPaths) {
    $relativePath = $filePath.Substring(
        $root.Length
    ).TrimStart("\").Replace("\", "/")

    $outputAuditHashes[$relativePath] = [ordered]@{
        sha256 = Get-FileSha256 -Path $filePath
        size_bytes = (Get-Item $filePath).Length
    }
}

$postchangeAudit = [ordered]@{
    version = $version
    phase = "DPIIT Governed Field Extraction and Evidence Validation Pilot"
    execution_mode = "MANUAL_PREVIEW_ONLY"
    baseline_recorded_at = $baseline.recorded_at
    validation_status = $overallStatus
    frozen_files = $frozenFileResults
    frozen_trees = $frozenTreeResults
    phase_output_files = $outputAuditHashes
}

Write-DeterministicJson `
  -Object $postchangeAudit `
  -Path $postchangeAuditPath

Write-Host ""
Write-Host "DPIIT v3.4.1.0.4 finalization"
Write-Host "----------------------------------------"
Write-Host "Validation status: $overallStatus"
Write-Host "Pilot records:     $($pilotRecords.Count)"
Write-Host "Evidence rows:     $($evidenceRows.Count)"
Write-Host "Review rows:       $($reviewRows.Count)"
Write-Host "Catalogue rows:    $($activeCatalogueRows.Count)"
Write-Host "Visible records:   $dashboardVisibleCount"
Write-Host "Published rows:    $($publishedCatalogueRows.Count)"
Write-Host ""
Write-Host "Validation:"
Write-Host $validationPath
Write-Host ""
Write-Host "Summary:"
Write-Host $summaryPath
Write-Host ""
Write-Host "Manifest:"
Write-Host $manifestPath
Write-Host ""
Write-Host "Post-change audit:"
Write-Host $postchangeAuditPath

if ($overallStatus -ne "PASS") {
    Write-Host ""
    Write-Host "Failed checks:"
    $failedChecks |
    ForEach-Object {
        Write-Host " - $_"
    }

    throw "DPIIT v3.4.1.0.4 validation failed."
}