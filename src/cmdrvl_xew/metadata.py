"""Extract issuer and filing metadata from iXBRL documents.

This module parses Document and Entity Information (DEI) facts and filing
headers from primary iXBRL documents to extract required metadata for
Evidence Pack generation.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class MetadataExtractionError(Exception):
    """Exception raised during metadata extraction."""
    pass


@dataclass
class EntityInfo:
    """Entity information extracted from iXBRL."""
    registrant_name: Optional[str] = None
    legal_name: Optional[str] = None
    cik: Optional[str] = None
    ticker_symbol: Optional[str] = None
    entity_scheme: Optional[str] = None
    entity_identifier: Optional[str] = None
    sic_code: Optional[str] = None
    current_reporting_status: Optional[str] = None


@dataclass
class FilingInfo:
    """Filing information extracted from iXBRL."""
    document_type: Optional[str] = None
    document_period_end_date: Optional[str] = None
    filed_as_of_date: Optional[str] = None
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    amendment_flag: Optional[bool] = None
    amendment_number: Optional[int] = None


@dataclass
class ExtractedMetadata:
    """Combined metadata extracted from iXBRL."""
    entity: EntityInfo = field(default_factory=EntityInfo)
    filing: FilingInfo = field(default_factory=FilingInfo)
    source_provenance: Dict[str, str] = field(default_factory=dict)  # field -> source
    extraction_timestamp: Optional[str] = None
    primary_document_path: Optional[str] = None


# Common DEI fact patterns (concept names)
DEI_CONCEPTS = {
    # Entity information
    'entity_registrant_name': [
        'dei:EntityRegistrantName',
        'dei:LegalEntityName',
        'dei:EntityName'
    ],
    'entity_cik': [
        'dei:EntityCentralIndexKey',
        'dei:CentralIndexKey'
    ],
    'entity_ticker': [
        'dei:TradingSymbol',
        'dei:EntityCommonStockSharesOutstanding',
        'dei:CommonStockSymbol'
    ],
    'entity_sic': [
        'dei:EntityWellKnownSeasonedIssuerStatus',
        'dei:EntityInformationSICCode'
    ],
    'current_reporting_status': [
        'dei:EntityCurrentReportingStatus'
    ],

    # Filing information
    'document_type': [
        'dei:DocumentType'
    ],
    'period_end_date': [
        'dei:DocumentPeriodEndDate'
    ],
    'filed_as_of_date': [
        'dei:DocumentFiledDate',
        'dei:FiledAsOfDate'
    ],
    'fiscal_year': [
        'dei:DocumentFiscalYearFocus',
        'dei:FiscalYear'
    ],
    'fiscal_period': [
        'dei:DocumentFiscalPeriodFocus',
        'dei:FiscalPeriod'
    ],
    'fiscal_year_end': [
        'dei:CurrentFiscalYearEndDate'
    ],
    'amendment_flag': [
        'dei:AmendmentFlag'
    ]
}


def extract_metadata(primary_path: Path) -> ExtractedMetadata:
    """
    Extract issuer and filing metadata from primary iXBRL document.

    Args:
        primary_path: Path to primary iXBRL HTML file

    Returns:
        ExtractedMetadata with entity and filing information

    Raises:
        MetadataExtractionError: If extraction fails or required metadata missing
    """
    if not primary_path.exists():
        raise MetadataExtractionError(f"Primary document not found: {primary_path}")

    logger.info(f"Extracting metadata from {primary_path}")

    try:
        content = _read_ixbrl_content(primary_path)
        facts = _extract_dei_facts(content)

        # Build metadata from extracted facts
        metadata = ExtractedMetadata()
        metadata.primary_document_path = str(primary_path)
        metadata.extraction_timestamp = datetime.utcnow().isoformat() + 'Z'

        _populate_entity_info(metadata.entity, facts, metadata.source_provenance)
        _populate_filing_info(metadata.filing, facts, metadata.source_provenance)

        logger.info(f"Successfully extracted metadata: entity={metadata.entity.registrant_name}, "
                   f"type={metadata.filing.document_type}, period={metadata.filing.document_period_end_date}")

        return metadata

    except Exception as e:
        raise MetadataExtractionError(f"Failed to extract metadata from {primary_path}: {e}") from e


def validate_against_cli_args(metadata: ExtractedMetadata,
                            cli_cik: str,
                            cli_form: str,
                            cli_filed_date: str) -> Dict[str, Any]:
    """
    Validate extracted metadata against CLI-provided values.

    Args:
        metadata: Extracted metadata
        cli_cik: CIK from CLI
        cli_form: Form type from CLI
        cli_filed_date: Filed date from CLI

    Returns:
        Dictionary with validation results and conflicts
    """
    conflicts = {}

    # Validate CIK
    if metadata.entity.cik and metadata.entity.cik != cli_cik:
        conflicts['cik'] = {
            'cli': cli_cik,
            'extracted': metadata.entity.cik,
            'field': 'entity.cik'
        }

    # Validate form type
    if metadata.filing.document_type and metadata.filing.document_type != cli_form:
        conflicts['form'] = {
            'cli': cli_form,
            'extracted': metadata.filing.document_type,
            'field': 'filing.document_type'
        }

    # Validate filed date (basic check)
    if (metadata.filing.filed_as_of_date and
        metadata.filing.filed_as_of_date != cli_filed_date):
        conflicts['filed_date'] = {
            'cli': cli_filed_date,
            'extracted': metadata.filing.filed_as_of_date,
            'field': 'filing.filed_as_of_date'
        }

    return {
        'has_conflicts': len(conflicts) > 0,
        'conflicts': conflicts,
        'validation_timestamp': datetime.utcnow().isoformat() + 'Z'
    }


def _read_ixbrl_content(path: Path) -> str:
    """Read iXBRL content with encoding tolerance."""
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        raise MetadataExtractionError(f"Could not read iXBRL file {path}: {e}") from e


def _extract_dei_facts(content: str) -> Dict[str, List[str]]:
    """
    Extract DEI facts from iXBRL content using regex patterns.

    Returns dictionary mapping concept names to values.
    """
    facts = {}

    # Pattern to match XBRL facts with DEI concepts
    # Handles both self-closing and regular tags
    fact_pattern = re.compile(
        r'<(?:ix:)?(?:nonFraction|nonNumeric|fraction)\b[^>]*?'
        r'name\s*=\s*["\']([^"\']*dei:[^"\']*)["\'][^>]*?'
        r'(?:/>|>([^<]*)</(?:ix:)?(?:nonFraction|nonNumeric|fraction)>)',
        re.IGNORECASE | re.DOTALL
    )

    # Also try simpler pattern for facts without ix: prefix
    simple_fact_pattern = re.compile(
        r'<([^>]*dei:[^>]*)\b[^>]*?'
        r'(?:/>|>([^<]*)</[^>]+>)',
        re.IGNORECASE | re.DOTALL
    )

    # Extract using both patterns
    for pattern in [fact_pattern, simple_fact_pattern]:
        matches = pattern.findall(content)
        for match in matches:
            if isinstance(match, tuple) and len(match) >= 2:
                concept_name = match[0].strip()
                value = match[1].strip() if match[1] else ''
            else:
                concept_name = match.strip()
                value = ''

            # Extract just the concept name (after colon)
            if ':' in concept_name:
                concept_key = concept_name.split(':')[-1]
            else:
                concept_key = concept_name

            if concept_key and value:
                if concept_name not in facts:
                    facts[concept_name] = []
                facts[concept_name].append(value)

    logger.debug(f"Extracted {len(facts)} DEI facts")
    return facts


def _populate_entity_info(entity: EntityInfo, facts: Dict[str, List[str]],
                         provenance: Dict[str, str]) -> None:
    """Populate entity information from extracted facts."""

    # Entity registrant name
    for concept_name in DEI_CONCEPTS['entity_registrant_name']:
        if concept_name in facts and facts[concept_name]:
            entity.registrant_name = facts[concept_name][0]
            entity.legal_name = entity.registrant_name  # Use as legal name too
            provenance['registrant_name'] = concept_name
            break

    # CIK
    for concept_name in DEI_CONCEPTS['entity_cik']:
        if concept_name in facts and facts[concept_name]:
            cik_value = facts[concept_name][0]
            # Normalize CIK (pad to 10 digits)
            if cik_value.isdigit():
                entity.cik = cik_value.zfill(10)
                provenance['cik'] = concept_name
            break

    # Ticker symbol
    for concept_name in DEI_CONCEPTS['entity_ticker']:
        if concept_name in facts and facts[concept_name]:
            entity.ticker_symbol = facts[concept_name][0]
            provenance['ticker_symbol'] = concept_name
            break

    # Set entity scheme/identifier
    if entity.cik:
        entity.entity_scheme = "http://www.sec.gov/CIK"
        entity.entity_identifier = entity.cik


def _populate_filing_info(filing: FilingInfo, facts: Dict[str, List[str]],
                         provenance: Dict[str, str]) -> None:
    """Populate filing information from extracted facts."""

    # Document type
    for concept_name in DEI_CONCEPTS['document_type']:
        if concept_name in facts and facts[concept_name]:
            filing.document_type = facts[concept_name][0]
            provenance['document_type'] = concept_name
            break

    # Period end date
    for concept_name in DEI_CONCEPTS['period_end_date']:
        if concept_name in facts and facts[concept_name]:
            date_value = facts[concept_name][0]
            # Normalize date format (basic validation)
            if _is_valid_date_format(date_value):
                filing.document_period_end_date = date_value
                provenance['period_end_date'] = concept_name
            break

    # Filed as of date
    for concept_name in DEI_CONCEPTS['filed_as_of_date']:
        if concept_name in facts and facts[concept_name]:
            date_value = facts[concept_name][0]
            if _is_valid_date_format(date_value):
                filing.filed_as_of_date = date_value
                provenance['filed_as_of_date'] = concept_name
            break

    # Fiscal year
    for concept_name in DEI_CONCEPTS['fiscal_year']:
        if concept_name in facts and facts[concept_name]:
            year_value = facts[concept_name][0]
            if year_value.isdigit():
                filing.fiscal_year = int(year_value)
                provenance['fiscal_year'] = concept_name
            break

    # Fiscal period
    for concept_name in DEI_CONCEPTS['fiscal_period']:
        if concept_name in facts and facts[concept_name]:
            filing.fiscal_period = facts[concept_name][0]
            provenance['fiscal_period'] = concept_name
            break

    # Amendment flag
    for concept_name in DEI_CONCEPTS['amendment_flag']:
        if concept_name in facts and facts[concept_name]:
            flag_value = facts[concept_name][0].lower()
            filing.amendment_flag = flag_value in ['true', '1', 'yes']
            provenance['amendment_flag'] = concept_name
            break


def _is_valid_date_format(date_str: str) -> bool:
    """Basic validation for date format (YYYY-MM-DD)."""
    if not date_str:
        return False

    # Check for basic date pattern
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    return bool(date_pattern.match(date_str.strip()))