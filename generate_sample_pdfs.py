"""Generate fictional supplier RFP responses (brief section 7) into sample_pdfs/.

All companies, people and numbers are invented. Author: Rudresh.
    python generate_sample_pdfs.py
"""
from html import escape
from pathlib import Path

import pymupdf

OUT = Path(__file__).parent / "sample_pdfs"
RFP = "RFP-2026-017: Cloud Procurement Analytics Platform for Northwind Retail Group"

CSS = """
* { font-family: sans-serif; font-size: 10pt; line-height: 1.35; }
h1 { font-size: 17pt; color: #17304f; margin-bottom: 2pt; }
h2 { font-size: 12.5pt; color: #1f5fbf; margin-top: 12pt; margin-bottom: 4pt; }
p { margin-top: 0; margin-bottom: 6pt; }
.meta { color: #555; font-size: 9pt; }
table { border-collapse: collapse; width: 100%; margin-bottom: 6pt; }
th { background-color: #17304f; color: white; text-align: left; padding: 3pt; font-size: 9pt; }
td { border: 1px solid #bbb; padding: 3pt; font-size: 9pt; }
li { margin-bottom: 2pt; }
"""

SUPPLIERS = {
    "Apex Systems": {
        "date": "2026-03-02",
        "summary": [
            "Apex Systems proposes a cloud-native procurement analytics platform built on a microservices architecture "
            "deployed across two availability zones on Azure. Our design prioritises security, scalability and deep "
            "integration with Northwind's SAP S/4HANA, Coupa and Snowflake estate.",
            "We understand Northwind needs a single source of truth for spend, supplier performance and contract "
            "compliance across 14 business units, replacing 30+ spreadsheets and a legacy Cognos deployment.",
        ],
        "solution": [
            "Architecture: event-driven ingestion using Kafka connectors, a medallion data lakehouse (bronze/silver/gold) "
            "on Delta Lake, and a GraphQL API layer. Pre-built, certified connectors for SAP S/4HANA (OData + IDoc), "
            "Coupa REST API, Workday and Snowflake secure data sharing. All integrations are bidirectional with retry "
            "queues and dead-letter handling.",
            "Scalability: horizontally autoscaled Kubernetes (AKS) services, load tested to 50 million spend lines and "
            "2,000 concurrent users with p95 dashboard latency under 1.8 seconds. Multi-region disaster recovery with "
            "RPO 15 minutes and RTO 2 hours.",
            "Analytics: spend cube, supplier scorecards, contract leakage detection and a forecasting module using "
            "gradient-boosted models, with lineage visible from every dashboard tile back to source records.",
        ],
        "timeline": [("Discovery & architecture sign-off", "Weeks 1-3", "Solution design approved"),
                     ("Integration build (SAP, Coupa, Workday)", "Weeks 4-11", "Data flowing into silver layer"),
                     ("Analytics & dashboards", "Weeks 9-15", "UAT-ready dashboards"),
                     ("Security testing & UAT", "Weeks 16-18", "Pen test passed, UAT sign-off"),
                     ("Go-live & hypercare", "Weeks 19-20", "Production go-live")],
        "team": "Engagement lead, solution architect, 2 data engineers, 2 integration engineers, security engineer, "
                "BI developer, QA analyst (9 FTE at peak). Named architect: Dr. Lena Moravec (12 years data platforms).",
        "prices": [("Platform licence (3 years)", "$540,000"), ("Implementation services", "$410,000"),
                   ("Integration connectors (4)", "$120,000"), ("Security hardening & pen testing", "$60,000"),
                   ("Training & change management", "$45,000"), ("Premium support (3 years)", "$165,000")],
        "total": "$1,340,000",
        "assumptions": ["Prices exclude Azure consumption, estimated at $6,500/month.",
                        "Northwind provides SAP and Coupa sandbox access by week 3.",
                        "Fixed price for listed scope; change requests billed at $1,650/day."],
        "security": ["ISO/IEC 27001:2022 certified (certificate IS-778120) and SOC 2 Type II report (Dec 2025) available under NDA.",
                     "AES-256 encryption at rest, TLS 1.3 in transit, customer-managed keys in Azure Key Vault.",
                     "SSO via Azure AD / SAML 2.0, role-based and row-level security by business unit.",
                     "Immutable audit logs retained for 7 years; GDPR data processing agreement and EU data residency.",
                     "Quarterly third-party penetration tests; critical vulnerabilities patched within 72 hours."],
        "risks": ["Risk register maintained weekly with owners and mitigations.",
                  "Key risk: delayed sandbox access - mitigated by mock data contracts from week 1."],
        "support": "Business-hours support (08:00-18:00 CET) with 4-hour response for P1 incidents; 24x7 available "
                   "as an add-on. Named customer success manager and quarterly service reviews.",
        "experience": "Delivered 11 procurement analytics platforms since 2019, including for a European grocery chain "
                      "(9,000 suppliers) and a logistics group.",
        "references": ["Helvetia Foods AG - Head of Procurement Analytics (contact on request)",
                       "TransEuro Logistics - CIO office (contact on request)"],
    },
    "BrightPath Tech": {
        "date": "2026-02-26",
        "summary": [
            "BrightPath Tech offers a fast, affordable way to get procurement dashboards live in weeks, not months. "
            "We use a low-code analytics stack that lets Northwind see spend data quickly and cheaply.",
            "We understand Northwind wants better visibility of spend and supplier performance.",
        ],
        "solution": [
            "We will deploy our BrightBoard SaaS product, pre-configured with standard procurement dashboards. Data is "
            "loaded from CSV exports that Northwind uploads weekly; an API connector for SAP is on our roadmap.",
            "The platform runs on a single-region cloud deployment and is suitable for most mid-sized customers. "
            "Performance testing for Northwind's data volume has not yet been carried out.",
        ],
        "timeline": [("Kick-off & data upload", "Weeks 1-2", "First data loaded"),
                     ("Dashboard configuration", "Weeks 3-8", "Dashboards live"),
                     ("Training & go-live", "Weeks 9-12", "Go-live")],
        "team": "Project manager (part-time) and 2 consultants.",
        "prices": [("BrightBoard subscription (3 years)", "$270,000"), ("Setup & configuration", "$85,000"),
                   ("Training (remote)", "$15,000")],
        "total": "$370,000",
        "assumptions": ["CSV exports are prepared and cleaned by Northwind.",
                        "Additional connectors and custom dashboards are quoted separately."],
        "security": ["We follow industry best practices for security.",
                     "Data is encrypted. ISO 27001 certification is planned for 2027.",
                     "Password login; SSO is available on the enterprise tier (not included in this price)."],
        "risks": [],
        "support": "Email support during business hours (US Eastern time), best-effort response. A shared "
                   "customer community forum and a library of how-to videos are included. Phone support, named "
                   "account management and uptime SLAs are only available on the enterprise tier, which is not "
                   "part of this offer. Product updates are released monthly and applied automatically.",
        "experience": "BrightPath Tech was founded in 2024. We have completed two dashboard projects for "
                      "small e-commerce companies, each with fewer than 200 suppliers and a single business unit. "
                      "We have not yet delivered for a retailer of Northwind's size, but our team is highly "
                      "motivated and learns quickly. We are keen to make Northwind a flagship customer and will "
                      "offer a 10% discount on year-two subscription fees in exchange for a public case study.",
        "references": ["References available on request."],
    },
    "NexaWorks": {
        "date": "2026-03-02",
        "summary": [
            "NexaWorks proposes a balanced, low-risk delivery of a procurement analytics platform on AWS, combining a "
            "proven product with a disciplined, phased implementation and a strong run-and-support model.",
            "Our understanding: Northwind requires consolidated spend visibility across 14 business units, supplier "
            "performance scorecards and contract compliance reporting, with a smooth hand-over to internal teams.",
        ],
        "solution": [
            "Solution: NexaInsight platform on AWS (Redshift, Glue, QuickSight embedded) with standard connectors for "
            "SAP S/4HANA and Coupa, and a documented REST API for further integrations. Scales to 20 million spend "
            "lines in our current benchmark; larger volumes use Redshift concurrency scaling.",
            "Implementation approach: agile delivery in four phases with fortnightly demos, a joint steering committee "
            "and a documented RACI. Data quality rules are agreed in discovery and monitored continuously.",
        ],
        "timeline": [("Phase 0 - Mobilisation", "Weeks 1-2", "Project charter, RACI, risk register baseline"),
                     ("Phase 1 - Discovery & design", "Weeks 3-6", "Data model and KPI catalogue signed off"),
                     ("Phase 2 - Build (3 sprints)", "Weeks 7-14", "SAP + Coupa pipelines, 12 dashboards"),
                     ("Phase 3 - Test & training", "Weeks 15-18", "UAT sign-off, 60 users trained"),
                     ("Phase 4 - Go-live & hypercare", "Weeks 19-22", "Go-live wk 19, hypercare to wk 22")],
        "team": "Delivery director (steering), full-time project manager, solution architect, 2 data engineers, "
                "BI developer, test lead, change & training lead (8 FTE). Named PM: Samuel Okafor, PMP, "
                "7 similar programmes.",
        "prices": [("NexaInsight licence (3 years)", "$390,000"), ("Implementation (fixed price)", "$285,000"),
                   ("Connectors SAP + Coupa", "$60,000"), ("Training & change management", "$40,000"),
                   ("24x7 support & managed service (3 years)", "$120,000")],
        "total": "$895,000",
        "assumptions": ["AWS consumption estimated at $4,200/month and billed at cost.",
                        "Fixed price covers the listed scope; 10% contingency held for agreed change requests.",
                        "Milestone-based payments: 20% / 30% / 30% / 20%."],
        "security": ["SOC 2 Type I report available; SOC 2 Type II audit window in progress (report due Q3 2026).",
                     "Encryption at rest (AWS KMS) and in transit (TLS 1.2+); SSO via SAML 2.0.",
                     "Role-based access by business unit; audit logging of all user and admin actions.",
                     "GDPR DPA provided; data hosted in AWS eu-west-1."],
        "risks": ["Weekly risk and issue review with the steering committee; top risks with owners and dates.",
                  "Data quality risk mitigated through automated validation rules and a data-owner sign-off gate.",
                  "Resource risk mitigated with a named backup for each key role."],
        "support": "24x7 support with contractual SLAs: P1 response 30 minutes / restore 4 hours, P2 response 2 hours. "
                   "Dedicated technical account manager, monthly service reports, 90-day hypercare, "
                   "and a knowledge-transfer plan so Northwind can self-serve new dashboards.",
        "experience": "Six procurement analytics implementations in retail and consumer goods since 2020.",
        "references": ["Baltic Home Retail - Procurement Director, Maria Lind",
                       "GreenLeaf Consumer Goods - Head of Data, Arun Patel"],
    },
    "Orbit Digital": {
        "date": "2026-02-28",
        "summary": [
            "Orbit Digital brings 15 years of procurement transformation experience and more than 40 analytics "
            "deployments for retailers across Europe and North America.",
            "We understand Northwind seeks improved spend visibility and supplier management across its business units.",
        ],
        "solution": [
            "We will implement our OrbitSpend analytics suite, a mature product used by large retailers. OrbitSpend "
            "will integrate with Northwind's existing systems as needed; the integration approach and connectors "
            "will be finalised during the discovery phase.",
            "The platform is hosted on Google Cloud and supports enterprise data volumes.",
        ],
        "timeline": [("Discovery", "Weeks 1-6", "Requirements confirmed"),
                     ("Implementation", "Weeks 7-20", "Platform configured"),
                     ("Go-live", "Weeks 21-24", "Go-live")],
        "team": "Account director, project manager and consultants from our retail practice, sized after discovery.",
        "prices": [("OrbitSpend licence (3 years)", "$450,000"), ("Implementation services (estimate)", "$320,000"),
                   ("Integration (estimate, to be confirmed)", "$90,000"), ("Support (3 years)", "$105,000")],
        "total": "$965,000 (estimate)",
        "assumptions": ["Integration and implementation costs are estimates until discovery is complete.",
                        "Travel expenses billed separately."],
        "security": ["ISO/IEC 27001 certified. Data encrypted at rest and in transit.",
                     "SSO supported. Hosted in Google Cloud europe-west regions."],
        "risks": ["Standard project risk management applies."],
        "support": "Business-hours support with 8-hour response for critical issues; customer success reviews twice a year.",
        "experience": "Over 40 procurement analytics deployments since 2011, including 12 retailers with more than "
                      "$1B annual spend. Winner of the 2025 Procurement Tech Excellence Award.",
        "references": ["Nordic Fashion Group - CPO, Erik Johansson (+46 8 555 0101)",
                       "Maple Grocers Canada - VP Procurement, Diane Chen (+1 416 555 0144)",
                       "Iberia Home Stores - Procurement Excellence Lead, Pablo Ruiz (+34 91 555 0199)"],
    },
}


def _ul(items):
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>" if items else "<p><i>Not provided.</i></p>"


def _table(head, rows):
    return ("<table><tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>")


def proposal_html(name, d):
    p = lambda paras: "".join(f"<p>{escape(x)}</p>" for x in paras)
    return f"""
<h1>{escape(name)} - Proposal</h1>
<p class="meta">Response to {escape(RFP)}<br/>Submission date: {d['date']} | Fictional document for classroom use</p>
<h2>1. Executive Summary &amp; Understanding of Requirement</h2>{p(d['summary'])}
<h2>2. Proposed Solution &amp; Implementation Approach</h2>{p(d['solution'])}
<h2>3. Timeline, Team Structure &amp; Milestones</h2>
{_table(["Phase", "Timing", "Milestone"], d['timeline'])}
<p><b>Team:</b> {escape(d['team'])}</p>
<h2>4. Pricing</h2>
{_table(["Item", "Cost (USD)"], d['prices'] + [("Total", d['total'])])}
<p><b>Assumptions:</b></p>{_ul(d['assumptions'])}
<h2>5. Security, Compliance &amp; Risk Controls</h2>{_ul(d['security'])}
<p><b>Risk management:</b></p>{_ul(d['risks'])}
<h2>6. Support Model, Experience &amp; References</h2>
<p><b>Support:</b> {escape(d['support'])}</p>
<p><b>Relevant experience:</b> {escape(d['experience'])}</p>
<p><b>References:</b></p>{_ul(d['references'])}
"""


def write_pdf(path, html, title):
    story = pymupdf.Story(html=html, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(path))
    mediabox = pymupdf.paper_rect("a4")
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(mediabox + (56, 56, -56, -56))
        story.draw(device)
        writer.end_page()
    writer.close()
    doc = pymupdf.open(path)
    doc.set_metadata({"title": title, "author": "Rudresh", "subject": RFP, "creator": "generate_sample_pdfs.py"})
    doc.saveIncr()
    doc.close()


def write_image_only_pdf(path):
    """Validation/error case: a 'scanned' proposal with no extractable text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(72, 72, 523, 160), color=(0.2, 0.2, 0.2), fill=(0.85, 0.85, 0.85))
    for y in range(200, 700, 18):
        page.draw_line((72, y), (72 + (y * 37 % 400) + 50, y), color=(0.6, 0.6, 0.6), width=6)
    doc.set_metadata({"title": "Scanned proposal (no text layer)", "author": "Rudresh"})
    doc.save(path)


# Tie-break demo pack: four IDENTICAL proposals (only the company name differs), so a consistent evaluator gives
# equal scores and equal PPI. The app enters dates/ratings so rules 2, 3 and 4 each decide one pair.
TWIN_NAMES = ["Delta Analytics", "Echo Analytics", "Foxtrot Analytics", "Golf Analytics"]
TWIN = {
    "date": "2026-02-24",
    "summary": ["We propose a standard procurement analytics service for Northwind based on our packaged dashboards, "
                "delivered by a small experienced team.",
                "We understand Northwind needs consolidated spend reporting and supplier scorecards across its business units."],
    "solution": ["Hosted analytics platform on Azure with a certified SAP S/4HANA connector and nightly CSV import for "
                 "Coupa. Tested with 10 million spend lines. Standard spend, supplier and contract dashboards.",
                 "Delivery follows a waterfall plan with a weekly status report and a monthly steering meeting."],
    "timeline": [("Design", "Weeks 1-4", "Design document approved"), ("Build", "Weeks 5-12", "Dashboards built"),
                 ("Test & train", "Weeks 13-15", "UAT sign-off"), ("Go-live", "Week 16", "Production go-live")],
    "team": "Project manager, solution architect, 2 data engineers, BI developer (5 FTE).",
    "prices": [("Licence (3 years)", "$360,000"), ("Implementation (fixed price)", "$240,000"),
               ("SAP connector", "$40,000"), ("Support (3 years)", "$90,000")],
    "total": "$730,000",
    "assumptions": ["Azure consumption billed at cost, estimated at $3,000/month.",
                    "Coupa data provided as nightly CSV exports by Northwind."],
    "security": ["ISO/IEC 27001 certified. Encryption at rest and in transit. SSO via SAML 2.0.",
                 "Role-based access; audit log retained for 1 year. GDPR DPA available."],
    "risks": ["Monthly risk review; top risks tracked in a shared register."],
    "support": "Business-hours support with 4-hour response for critical incidents; quarterly service reviews.",
    "experience": "Four procurement analytics projects for mid-sized retailers since 2021.",
    "references": ["Two retail references available after shortlisting."],
}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, d in SUPPLIERS.items():
        path = OUT / f"{name.replace(' ', '_')}.pdf"
        write_pdf(path, proposal_html(name, d), f"{name} proposal")
        print(f"{path.name}: {pymupdf.open(path).page_count} page(s)")
    write_image_only_pdf(OUT / "Scanned_NoText_Supplier.pdf")
    (OUT / "tiebreak_demo").mkdir(exist_ok=True)
    for name in TWIN_NAMES:
        write_pdf(OUT / "tiebreak_demo" / f"{name.replace(' ', '_')}.pdf", proposal_html(name, TWIN), f"{name} proposal")
    print(f"tiebreak_demo/: {len(TWIN_NAMES)} identical proposals")
    print("Scanned_NoText_Supplier.pdf: 1 page (image only, error case)")
