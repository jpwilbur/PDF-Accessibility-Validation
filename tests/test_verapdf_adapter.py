"""Tests for the veraPDF adapter — both XML parsing and the live subprocess."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_a11y.adapters import verapdf as vpdf

# ---------------------------------------------------------------------------
# Pure XML parsing (no subprocess required)
# ---------------------------------------------------------------------------

PASSING_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<report>
  <jobs><job>
    <validationReport profileName="PDF/UA-1 validation profile" isCompliant="true">
      <details passedRules="106" failedRules="0" passedChecks="42" failedChecks="0"/>
    </validationReport>
  </job></jobs>
</report>
"""

FAILING_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<report>
  <jobs><job>
    <validationReport profileName="PDF/UA-1 validation profile" isCompliant="false">
      <details passedRules="105" failedRules="1" passedChecks="780" failedChecks="2">
        <rule specification="ISO 14289-1:2014" clause="7.3" testNumber="2"
              status="failed" failedChecks="2" tags="figure">
          <description>Figure structure elements need /Alt or /ActualText</description>
          <object>SEFigure</object>
          <test>hasAlt or hasActualText</test>
          <check status="failed">
            <context>root/document[0]/.../Figure[3]</context>
            <errorMessage>Figure has no /Alt entry</errorMessage>
          </check>
          <check status="failed">
            <context>root/document[0]/.../Figure[7]</context>
            <errorMessage>Figure has no /Alt entry</errorMessage>
          </check>
        </rule>
      </details>
    </validationReport>
  </job></jobs>
</report>
"""


def test_parse_passing_xml() -> None:
    result = vpdf._parse_xml(PASSING_XML)
    assert result.is_compliant is True
    assert result.failed_rules == 0
    assert result.passed_rules == 106
    assert result.failures == []


def test_parse_failing_xml_extracts_locations() -> None:
    result = vpdf._parse_xml(FAILING_XML)
    assert result.is_compliant is False
    assert result.failed_rules == 1
    assert len(result.failures) == 1
    f = result.failures[0]
    assert f.key == "7.3-2"
    assert f.specification.startswith("ISO 14289")
    assert "Figure" in f.description
    assert f.tags == ("figure",)
    assert len(f.locations) == 2
    assert "Figure[3]" in f.locations[0].context
    assert f.locations[0].error_message == "Figure has no /Alt entry"


def test_parse_handles_missing_validation_report() -> None:
    bad = "<?xml version='1.0'?><report><jobs><job/></jobs></report>"
    result = vpdf._parse_xml(bad)
    assert result.error is not None


# ---------------------------------------------------------------------------
# Live subprocess (skipped when verapdf isn't on PATH)
# ---------------------------------------------------------------------------


@pytest.mark.needs_verapdf
def test_run_against_known_good(known_good_pdf: Path, has_verapdf: bool) -> None:
    if not has_verapdf:
        pytest.skip("verapdf not installed")
    result = vpdf.run(known_good_pdf)
    assert result.available is True
    assert result.error is None
    assert result.is_compliant is True


@pytest.mark.needs_verapdf
def test_run_against_known_bad_table(fixtures_dir: Path, has_verapdf: bool) -> None:
    if not has_verapdf:
        pytest.skip("verapdf not installed")
    pdf = fixtures_dir / "known_bad" / "verapdf-ua1-7.5-tables-fail.pdf"
    result = vpdf.run(pdf)
    assert result.available is True
    assert result.error is None
    assert result.is_compliant is False
    keys = {f.key for f in result.failures}
    # The fixture is named "7.5 tables fail" — expect at least one 7.5-* rule.
    assert any(k.startswith("7.5-") for k in keys)


@pytest.mark.needs_verapdf
def test_run_returns_unavailable_when_binary_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vpdf, "is_available", lambda: False)
    result = vpdf.run(tmp_path / "anything.pdf")
    assert result.available is False
    assert result.error is not None
