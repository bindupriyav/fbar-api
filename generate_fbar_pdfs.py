#!/usr/bin/env python3
"""
Renders one PDF per synthetic FBAR filing, laid out to mirror the structure of
FinCEN Form 114 (Report of Foreign Bank and Financial Accounts) as filed through
the BSA E-Filing System (https://bsaefiling.fincen.gov/file/fbar):

  Part I   - Filer Information
  Part II  - Financial Account(s) Owned Separately
  Part III - Financial Account(s) Owned Jointly
  Part IV  - Financial Account(s) with Signature/Other Authority, No Financial Interest
  Part V   - Consolidated Report reference (entity filers only, if applicable)

This is a SPECIMEN/TEST-FIXTURE renderer, not the official FinCEN form (which is
only filable through bsaefiling.fincen.gov). Every generated page carries a visible
"SYNTHETIC TEST DATA" banner so these can never be mistaken for a real filing.

After generating the PDFs, this script writes each file's size and SHA-256 back
into the source JSON as a `pdfDocument` block (the pointer a DynamoDB item would
store, per the AWS storage note in dynamodb_schema.md).
"""
import hashlib
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER

SRC_JSON = "synthetic_fbar_filings.json"
OUT_DIR = "pdfs"
os.makedirs(OUT_DIR, exist_ok=True)

styles = getSampleStyleSheet()
title_style = ParagraphStyle("FormTitle", parent=styles["Title"], fontSize=13, spaceAfter=2)
subtitle_style = ParagraphStyle("FormSubtitle", parent=styles["Normal"], fontSize=8.5,
                                 textColor=colors.HexColor("#444444"))
part_header_style = ParagraphStyle("PartHeader", parent=styles["Heading2"], fontSize=11,
                                    spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1a3d6d"))
banner_style = ParagraphStyle("Banner", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER,
                               textColor=colors.white, fontName="Helvetica-Bold")
normal = styles["Normal"]
small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#555555"))

FIELD_TABLE_STYLE = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])

def banner(text):
    t = Table([[Paragraph(text, banner_style)]], colWidths=[7.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#b91c1c")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t

def kv_table(rows, col_widths=None):
    data = [["Item", "Value"]] + rows
    t = Table(data, colWidths=col_widths or [2.3 * inch, 4.7 * inch])
    t.setStyle(FIELD_TABLE_STYLE)
    return t

def fmt_money(val, currency="USD"):
    if val is None:
        return "N/A"
    return f"{val:,.2f} {currency}"

def filer_name_display(filer):
    if filer["filerType"] == "Entity":
        return filer["name"]["entityName"]
    n = filer["name"]
    parts = [n.get("last", ""), n.get("first", "")]
    if n.get("middle"):
        parts.append(n["middle"])
    return f"{n.get('last','')}, {n.get('first','')}" + (f" {n['middle']}" if n.get("middle") else "")

def build_part1(filer):
    story = [Paragraph("Part I &mdash; Filer Information", part_header_style)]
    addr = filer["address"]
    if filer["filerType"] == "Individual":
        rows = [
            ["1  Filer Type", filer["filerType"]],
            ["2  U.S. Person Category", filer["usPersonCategory"]],
            ["3  TIN Type / TIN", f'{filer["tin"]["type"]} / {filer["tin"]["value"]}'],
            ["4  Last Name", filer["name"]["last"]],
            ["5  First Name", filer["name"]["first"]],
            ["6  Middle Name/Initial", filer["name"].get("middle") or ""],
            ["7  Date of Birth", filer.get("dateOfBirth", "")],
            ["8  Occupation", filer.get("occupation", "")],
            ["9  Address", addr["street"]],
            ["10 City", addr["city"]],
            ["11 State", addr.get("stateOrProvince", "")],
            ["12 ZIP/Postal Code", addr["zipOrPostal"]],
            ["13 Country", addr["country"]],
        ]
    else:
        rows = [
            ["1  Filer Type", filer["filerType"]],
            ["2  U.S. Person Category", filer["usPersonCategory"]],
            ["3  TIN Type / TIN", f'{filer["tin"]["type"]} / {filer["tin"]["value"]}'],
            ["4  Entity Legal Name", filer["name"]["entityName"]],
            ["5  Entity Type", filer.get("entityType", "")],
            ["9  Address", addr["street"]],
            ["10 City", addr["city"]],
            ["11 State", addr.get("stateOrProvince", "")],
            ["12 ZIP/Postal Code", addr["zipOrPostal"]],
            ["13 Country", addr["country"]],
        ]
    story.append(kv_table(rows))
    return story

def account_rows(acct, base_item=15):
    inst = acct["financialInstitution"]
    rows = [
        [f"{base_item}  Maximum Account Value", fmt_money(acct.get("maxAccountValueUSD"), acct.get("currency", "USD"))],
        [f"{base_item+1}  Type of Account", acct["accountType"] + (f' — {acct.get("accountTypeOtherDescription","")}' if acct.get("accountTypeOtherDescription") else "")],
        [f"{base_item+2}  Financial Institution Name", inst["name"]],
        [f"{base_item+3}  Account Number / Designation", acct["accountNumber"]],
        [f"{base_item+4}  Institution City", inst["address"]["city"]],
        [f"{base_item+5}  Institution Country", inst["address"]["country"]],
        [f"{base_item+6}  Account Closed During Year", "Yes" if acct.get("accountClosedDuringYear") else "No"],
    ]
    if acct.get("note"):
        rows.append([f"{base_item+7}  Note", acct["note"]])
    return rows

def build_part2(accounts):
    story = [Paragraph(f"Part II &mdash; Financial Account(s) Owned Separately ({len(accounts)})", part_header_style)]
    for i, acct in enumerate(accounts, start=1):
        story.append(Paragraph(f"Account {i} of {len(accounts)}", small))
        story.append(kv_table(account_rows(acct)))
        story.append(Spacer(1, 6))
    return story

def build_part3(accounts, joint_filers):
    story = [Paragraph(f"Part III &mdash; Financial Account(s) Owned Jointly ({len(accounts)})", part_header_style)]
    for i, acct in enumerate(accounts, start=1):
        story.append(Paragraph(f"Joint Account {i} of {len(accounts)}  &mdash;  {acct.get('jointOwnerCount', len(joint_filers))} joint owner(s)", small))
        story.append(kv_table(account_rows(acct)))
        for j, jf in enumerate(joint_filers, start=1):
            jname = jf["name"]
            jrows = [
                [f"Joint Owner {j} — Last Name", jname["last"]],
                [f"Joint Owner {j} — First Name", jname["first"]],
                [f"Joint Owner {j} — TIN Type / TIN", f'{jf["tin"]["type"]} / {jf["tin"]["value"]}'],
                [f"Joint Owner {j} — Relationship to Filer", jf["relationship"]],
            ]
            story.append(kv_table(jrows))
        story.append(Spacer(1, 6))
    return story

def build_part4(accounts):
    story = [Paragraph(f"Part IV &mdash; Signature/Other Authority, No Financial Interest ({len(accounts)})", part_header_style)]
    for i, acct in enumerate(accounts, start=1):
        story.append(Paragraph(f"Account {i} of {len(accounts)}", small))
        story.append(kv_table(account_rows(acct)))
        story.append(Spacer(1, 6))
    return story

def build_signature_block(filing):
    sig = filing["signature"]
    story = [Paragraph("Signature", part_header_style)]
    rows = [
        ["Signed", "Yes" if sig.get("signed") else "No"],
        ["Signature Date", sig.get("signatureDate", "")],
        ["Preparer Used", "Yes" if sig.get("preparerUsed") else "No"],
    ]
    if sig.get("preparerPtin"):
        rows.append(["Preparer PTIN", sig["preparerPtin"]])
    story.append(kv_table(rows))
    return story

def build_pdf(filing, out_path):
    doc = SimpleDocTemplate(out_path, pagesize=letter,
                             topMargin=0.55 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.65 * inch, rightMargin=0.65 * inch)
    story = []
    story.append(banner("SYNTHETIC TEST DATA \u2014 SPECIMEN ONLY \u2014 NOT AN OFFICIAL FINCEN FILING"))
    story.append(Spacer(1, 8))
    story.append(Paragraph("FinCEN Form 114 &mdash; Report of Foreign Bank and Financial Accounts (FBAR)", title_style))
    story.append(Paragraph(
        f"BSA Identifier: {filing['bsaId']}  |  Submission Type: {filing['submissionType']}  |  "
        f"Filing Status: {filing['filingStatus']}  |  Tax Year: {filing['taxYear']}  |  "
        f"Date Filed: {filing['dateFiled']}",
        subtitle_style
    ))
    story.append(Paragraph(
        "Rendered from a synthetic case-management test fixture, formatted to mirror the field layout of the "
        "BSA E-Filing System's FBAR submission (bsaefiling.fincen.gov/file/fbar). All names, TINs, account "
        "numbers, and institutions on this page are fictional.",
        small
    ))
    story.append(Spacer(1, 6))

    story.extend(build_part1(filing["filer"]))

    if filing.get("priorReportBsaId"):
        story.append(kv_table([["Prior Report BSA ID (Amends)", filing["priorReportBsaId"]]]))
    if filing.get("supersededByBsaId"):
        story.append(kv_table([["Superseded By BSA ID", filing["supersededByBsaId"]]]))
    if filing.get("amendmentReason"):
        story.append(kv_table([["Amendment Reason", filing["amendmentReason"]]]))
    if filing.get("rejectReason"):
        story.append(kv_table([["Reject Reason", filing["rejectReason"]]]))
    if filing.get("lateFilingReasonCode"):
        story.append(kv_table([["Late Filing Reason Code", filing["lateFilingReasonCode"]]]))

    accounts = filing["financialAccounts"]
    part4_accts = [a for a in accounts if a["accountType"] == "SignatureAuthorityOnly"]
    joint_accts = [a for a in accounts if a is not part4_accts and a.get("jointOwnerCount", 0) > 0 and a["accountType"] != "SignatureAuthorityOnly"]
    separate_accts = [a for a in accounts if a["accountType"] != "SignatureAuthorityOnly" and a.get("jointOwnerCount", 0) == 0]

    if separate_accts:
        story.append(PageBreak())
        story.extend(build_part2(separate_accts))
    if joint_accts:
        story.append(PageBreak() if separate_accts else Spacer(1, 4))
        story.extend(build_part3(joint_accts, filing.get("jointFilers", [])))
    if part4_accts:
        story.append(PageBreak() if (separate_accts or joint_accts) else Spacer(1, 4))
        story.extend(build_part4(part4_accts))

    story.append(Spacer(1, 10))
    story.extend(build_signature_block(filing))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "This document is a synthetic test artifact generated for QA/integration testing of a case management "
        "system. It is not a real FBAR submission and has no legal filing status with FinCEN.",
        small
    ))

    doc.build(story)

def main():
    with open(SRC_JSON) as f:
        data = json.load(f)

    for filing in data["filings"]:
        file_name = f"FBAR_{filing['bsaId']}.pdf"
        out_path = os.path.join(OUT_DIR, file_name)
        build_pdf(filing, out_path)

        size_bytes = os.path.getsize(out_path)
        sha256 = hashlib.sha256(open(out_path, "rb").read()).hexdigest()

        filing["pdfDocument"] = {
            "fileName": file_name,
            "s3Bucket": "irs-cm-fbar-documents-dev",
            "s3Key": f"fbar-pdfs/{filing['taxYear']}/{file_name}",
            "contentType": "application/pdf",
            "sizeBytes": size_bytes,
            "sha256": sha256,
            "generatedFrom": "synthetic_fbar_filings.json",
            "note": "Specimen PDF rendered to mirror the FinCEN Form 114 field layout; not an official FinCEN document."
        }

    with open(SRC_JSON, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Generated {len(data['filings'])} PDFs in ./{OUT_DIR}/ and updated {SRC_JSON}")

if __name__ == "__main__":
    main()
