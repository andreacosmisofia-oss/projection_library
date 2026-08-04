"""Unit tests for the iXBRL extractor — no network, no files."""

import pytest
from ch_labels.extract import extract_ixbrl, _collect_text, _qname_parts
from lxml import etree


IXBRL_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:uk-core="http://xbrl.frc.org.uk/fr/2023-01-01/core"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <body>
    <ix:header>
      <ix:references/>
      <ix:resources>
        <xbrli:context id="c1">
          <xbrli:entity><xbrli:identifier scheme="http://www.companieshouse.gov.uk">12345678</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:unit id="u1"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
      </ix:resources>
    </ix:header>
    <p>Turnover: <ix:nonFraction name="uk-core:Turnover" contextRef="c1" unitRef="u1" decimals="-3">1500</ix:nonFraction></p>
    <p>Company name: <ix:nonNumeric name="uk-core:EntityCurrentLegalOrRegisteredName" contextRef="c1">Acme Ltd</ix:nonNumeric></p>
  </body>
</html>"""


def test_extract_ixbrl_returns_rows():
    rows = extract_ixbrl(IXBRL_SAMPLE, "test.html")
    assert len(rows) >= 2


def test_extract_labels():
    rows = extract_ixbrl(IXBRL_SAMPLE, "test.html")
    labels = {r["label"] for r in rows}
    assert "1500" in labels or "Turnover" in labels or any("1500" in l for l in labels)
    assert any("Acme" in r["label"] for r in rows)


def test_extract_tags():
    rows = extract_ixbrl(IXBRL_SAMPLE, "test.html")
    tags = {r["tag"] for r in rows}
    assert any("Turnover" in t or "uk-core" in t for t in tags)


def test_extract_period():
    rows = extract_ixbrl(IXBRL_SAMPLE, "test.html")
    periods = {r["period"] for r in rows}
    assert "2023-12-31" in periods


def test_qname_parts_braces():
    ns, local = _qname_parts("{http://example.com/ns}ElementName")
    assert ns == "http://example.com/ns"
    assert local == "ElementName"


def test_qname_parts_prefix():
    ns, local = _qname_parts("uk-core:Turnover")
    assert ns == "uk-core"
    assert local == "Turnover"


def test_collect_text_skips_hidden():
    html = b"""<p xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
      Visible<span style="display:none">hidden</span> text
    </p>"""
    root = etree.fromstring(html)
    text = _collect_text(root)
    assert "Visible" in text
    assert "hidden" not in text
