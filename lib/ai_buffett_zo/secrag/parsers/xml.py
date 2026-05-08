"""XML → readable text for SEC structured filings (primarily Form 4).

Form 4 (insider transactions) is XML, not HTML. The structured fields —
issuer name + CIK, reporting person name + relationship, transaction
table (date, code, shares, price, post-transaction holdings) — get
flattened into a markdown-style report so the indexed text is human-readable
and keyword-searchable.

Schema reference: https://www.sec.gov/info/edgar/specifications/ownershipxml.html

Implementation uses stdlib `xml.etree.ElementTree` (no `lxml` dependency).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def parse_xml(content: str) -> str:
    """Convert XML (typically Form 4) into a markdown-style report.

    Always returns a non-empty string when given parseable XML — even unfamiliar
    schemas fall through to a flat text dump to preserve searchability.
    """
    cleaned = _strip_xml_namespaces(content)
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        return ""

    if root.tag == "ownershipDocument":
        return _parse_ownership_doc(root)
    return _generic_xml_to_markdown(root)


def _parse_ownership_doc(root: ET.Element) -> str:
    """Form 3/4/5 ownership document → markdown report."""
    parts: list[str] = []

    form_type = _text(root, "documentType") or "Ownership"
    parts.append(f"# Form {form_type}")
    parts.append("")

    period = _text(root, "periodOfReport")
    if period:
        parts.append(f"**Period of report:** {period}")

    issuer_name = _text(root, ".//issuer/issuerName")
    issuer_cik = _text(root, ".//issuer/issuerCik")
    issuer_symbol = _text(root, ".//issuer/issuerTradingSymbol")
    if issuer_name:
        parts.append("")
        parts.append("## Issuer")
        parts.append(f"- Name: {issuer_name}")
        if issuer_symbol:
            parts.append(f"- Symbol: {issuer_symbol}")
        if issuer_cik:
            parts.append(f"- CIK: {issuer_cik}")

    owners = root.findall(".//reportingOwner")
    if owners:
        parts.append("")
        parts.append("## Reporting owner(s)")
        for o in owners:
            name = _text(o, ".//rptOwnerName")
            rel = o.find("reportingOwnerRelationship")
            roles: list[str] = []
            if rel is not None:
                if _is_true(rel, "isDirector"):
                    roles.append("Director")
                if _is_true(rel, "isOfficer"):
                    title = _text(rel, "officerTitle")
                    roles.append(f"Officer ({title})" if title else "Officer")
                if _is_true(rel, "isTenPercentOwner"):
                    roles.append("10% owner")
                if _is_true(rel, "isOther"):
                    other = _text(rel, "otherText")
                    roles.append(f"Other ({other})" if other else "Other")
            line = f"- {name}" if name else "- (unnamed)"
            if roles:
                line += " — " + ", ".join(roles)
            parts.append(line)

    nd_transactions = root.findall(".//nonDerivativeTransaction")
    if nd_transactions:
        parts.append("")
        parts.append("## Non-derivative transactions")
        parts.append("")
        parts.append("| Date | Code | Shares | Acquired/Disposed | Price | Post-tx holdings | Security |")
        parts.append("| --- | --- | --- | --- | --- | --- | --- |")
        for tx in nd_transactions:
            date = _value(tx, ".//transactionDate")
            code = _value(tx, ".//transactionCode")
            shares = _value(tx, ".//transactionShares")
            ad = _value(tx, ".//transactionAcquiredDisposedCode")
            price = _value(tx, ".//transactionPricePerShare")
            post = _value(tx, ".//sharesOwnedFollowingTransaction")
            security = _value(tx, ".//securityTitle")
            parts.append(
                f"| {date or '—'} | {code or '—'} | {shares or '—'} | "
                f"{ad or '—'} | {price or '—'} | {post or '—'} | {security or '—'} |"
            )

    d_transactions = root.findall(".//derivativeTransaction")
    if d_transactions:
        parts.append("")
        parts.append("## Derivative transactions")
        parts.append("")
        parts.append("| Date | Code | Shares | Acquired/Disposed | Strike | Underlying | Security |")
        parts.append("| --- | --- | --- | --- | --- | --- | --- |")
        for tx in d_transactions:
            date = _value(tx, ".//transactionDate")
            code = _value(tx, ".//transactionCode")
            shares = _value(tx, ".//transactionShares")
            ad = _value(tx, ".//transactionAcquiredDisposedCode")
            strike = _value(tx, ".//conversionOrExercisePrice")
            underlying_title = _value(tx, ".//underlyingSecurityTitle")
            security = _value(tx, ".//securityTitle")
            parts.append(
                f"| {date or '—'} | {code or '—'} | {shares or '—'} | "
                f"{ad or '—'} | {strike or '—'} | {underlying_title or '—'} | {security or '—'} |"
            )

    footnotes = root.findall(".//footnote")
    if footnotes:
        parts.append("")
        parts.append("## Footnotes")
        for f in footnotes:
            text = (f.text or "").strip()
            if not text:
                continue
            fid = f.get("id", "")
            parts.append(f"- ({fid}) {text}" if fid else f"- {text}")

    return "\n".join(parts).strip() + "\n"


def _generic_xml_to_markdown(root: ET.Element) -> str:
    """Fallback for XML schemas we don't have specific handling for."""
    parts: list[str] = [f"# {root.tag}", ""]
    parts.append(_concat_text(root))
    return "\n".join(parts).strip() + "\n"


def _concat_text(element: ET.Element) -> str:
    """Recursively join all text content of an element + its descendants."""
    fragments: list[str] = []
    if element.text:
        fragments.append(element.text.strip())
    for child in element:
        fragments.append(_concat_text(child))
        if child.tail:
            fragments.append(child.tail.strip())
    out = "\n".join(f for f in fragments if f)
    return re.sub(r"\n{3,}", "\n\n", out)


def _text(parent: ET.Element, path: str) -> str:
    """Get the stripped text content of the first element matching `path`.

    `path` accepts an ElementTree path (e.g., ".//issuerName" or "documentType").
    """
    el = parent.find(path)
    if el is None:
        return ""
    return (el.text or "").strip()


def _value(parent: ET.Element, path: str) -> str:
    """SEC ownership XML wraps values in <name><value>X</value></name>."""
    el = parent.find(path)
    if el is None:
        return ""
    val = el.find("value")
    if val is not None:
        return (val.text or "").strip()
    return (el.text or "").strip()


def _is_true(parent: ET.Element, path: str) -> bool:
    v = _text(parent, path).lower()
    return v in ("1", "true", "yes")


def _strip_xml_namespaces(content: str) -> str:
    """Strip xmlns declarations so ElementTree's tag names stay simple
    (avoids `{http://...}rptOwnerName`-style names in our finds)."""
    return re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", content)
