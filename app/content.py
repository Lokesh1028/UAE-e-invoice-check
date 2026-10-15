"""
Long-form pages for search engines and LLM crawlers. Facts reviewed 15 Oct 2026 against
Ministry of Finance publications (Ministerial Decisions 243 and 244 of 2025 as amended by
Ministerial Decision 66 of 2026, Cabinet Decision 106 of 2025) and the OpenPeppol PINT AE
1.0.2 specification. Update REVIEWED and the facts together.
"""
from __future__ import annotations

REVIEWED = "15 October 2026"

FAQ = [
    ("When does e-invoicing become mandatory in the UAE?",
     "Businesses with annual revenue of AED 50 million or more must appoint an Accredited Service Provider (ASP) by 30 October 2026 and go live on 1 January 2027. "
     "Businesses with revenue below AED 50 million must appoint an ASP by 31 March 2027 and go live on 1 July 2027. Government entities go live on 1 October 2027. "
     "A voluntary pilot phase has been open since 1 July 2026."),
    ("Who has to comply with UAE e-invoicing?",
     "Every person conducting business in the UAE for business-to-business (B2B) and business-to-government (B2G) transactions, whether or not they are registered for VAT. "
     "Business-to-consumer (B2C) sales are outside the current scope, and a few transactions are excluded (sovereign government activity, airline passenger tickets, certain zero-rated or exempt financial services)."),
    ("What format does a UAE e-invoice use?",
     "A structured XML file in the PINT AE format (the UAE specialisation of Peppol PINT, based on UBL 2.1), exchanged through Accredited Service Providers on the Peppol five-corner model. "
     "A PDF or a scanned invoice is not a valid e-invoice; it can only be a human-readable copy."),
    ("What are the penalties for not complying?",
     "Under Cabinet Decision 106 of 2025: AED 5,000 for each month (or part of a month) of delay in implementing e-invoicing or appointing an ASP, "
     "AED 100 for each e-invoice not issued or transmitted on time, and AED 1,000 per day for not notifying the authority of a system failure in time."),
    ("What is the difference between TRN and TIN?",
     "The TRN (Tax Registration Number) is the 15-digit VAT number, starting with 1 and ending with 03. The TIN (Tax Identification Number) is a 10-digit number starting with 1; "
     "with scheme 0235 it is your electronic address on the e-invoicing network. An e-invoice needs the TIN of both seller and buyer, and the TRN where the party is VAT registered."),
    ("Is this checker free, and do you keep my files?",
     "Yes, it is free with no sign-up. Uploaded files are processed in memory and are not stored. The check uses the official PINT AE 1.0.2 rule set and the UBL 2.1 schema."),
    ("Does passing this check mean I am compliant?",
     "It means the documents you uploaded would pass the published validation rules in their current form. Compliance also requires appointing an ASP, onboarding, and transmitting every in-scope invoice through it. This tool is not tax advice."),
]


GUIDE = f"""
<p class="lede">The UAE is replacing PDF and paper invoices between businesses with structured electronic invoices that are validated, exchanged through accredited providers and reported to the Federal Tax Authority (FTA) in near real time. This guide explains what changes, who is affected, the deadlines, the penalties and how to prepare, in plain language.</p>
<p class="meta">Last reviewed {REVIEWED}. Sources: UAE Ministry of Finance e-invoicing programme, Ministerial Decisions 243 and 244 of 2025 (as amended by Ministerial Decision 66 of 2026), Cabinet Decision 106 of 2025, OpenPeppol PINT AE 1.0.2. Not tax advice.</p>

<h2 id="what">What is changing</h2>
<p>Today an invoice is usually a document: made in Excel, Word, Tally or an accounting package, sent as a PDF by email or WhatsApp. The FTA only sees totals, through the quarterly VAT return.</p>
<p>Under the UAE e-invoicing system the legal invoice becomes a <strong>data record</strong>: an XML file in the <strong>PINT AE</strong> format with roughly 50 mandatory fields, checked against published business rules before it can be sent, delivered to the buyer through the Peppol network, and reported to the FTA at the same time. A PDF can still be shared for reading, but it is no longer the invoice.</p>

<h2 id="who">Who must comply</h2>
<ul>
<li><strong>All B2B and B2G transactions</strong> by persons conducting business in the UAE, mainland and free zone.</li>
<li><strong>VAT registration does not matter.</strong> A business below the VAT threshold that sells to other businesses is in scope too.</li>
<li><strong>Receiving is mandatory as well as sending.</strong> If your supplier sends you an e-invoice, you need a provider to receive it.</li>
</ul>
<p>Currently outside scope: B2C sales (expected later by a separate decision), government acting in a sovereign capacity, international airline passenger tickets, and certain zero-rated or exempt financial services.</p>

<h2 id="deadlines">Deadlines</h2>
<table>
<tr><th>Who</th><th>Appoint an ASP by</th><th>Go live (send and receive)</th></tr>
<tr><td>Any business, voluntary pilot</td><td>open now</td><td>from 1 July 2026</td></tr>
<tr><td>Revenue AED 50 million and above</td><td>30 October 2026</td><td>1 January 2027</td></tr>
<tr><td><strong>Revenue below AED 50 million</strong></td><td><strong>31 March 2027</strong></td><td><strong>1 July 2027</strong></td></tr>
<tr><td>Government entities</td><td>per Ministry timeline</td><td>1 October 2027</td></tr>
</table>
<p>The appointment deadline matters as much as go-live: onboarding and testing with a provider takes weeks, and missing the appointment date is a separate violation.</p>

<h2 id="how">How it works: the five-corner model</h2>
<ol>
<li><strong>Corner 1, the seller,</strong> creates the invoice in software that can produce PINT AE XML.</li>
<li><strong>Corner 2, the seller's Accredited Service Provider (ASP),</strong> validates it and sends it over the Peppol network.</li>
<li><strong>Corner 3, the buyer's ASP,</strong> validates it again and delivers it.</li>
<li><strong>Corner 4, the buyer,</strong> receives it into their software.</li>
<li><strong>Corner 5, the FTA,</strong> receives the tax data of every invoice from the ASPs.</li>
</ol>
<p>The buyer is found by their Peppol participant identifier: scheme <code>0235</code> plus their 10-digit TIN. You can check whether a business is already reachable with our <a href="/peppol-tin-lookup">Peppol TIN lookup</a>.</p>

<h2 id="asp">What an Accredited Service Provider is</h2>
<p>An ASP is a company approved by the Ministry of Finance to exchange e-invoices on the network and report them to the FTA. Accreditation requires Peppol certification, information-security certification and UAE registration, and the Ministry publishes the list of pre-approved providers. Most small businesses will reach an ASP through their accounting software or accountant rather than integrating directly.</p>

<h2 id="format">The PINT AE format</h2>
<ul>
<li>Syntax: UBL 2.1 XML (<code>Invoice</code> or <code>CreditNote</code>).</li>
<li>Specification identifier: <code>urn:peppol:pint:billing-1@ae-1</code>; business process: <code>urn:peppol:bis:billing</code>.</li>
<li>Rules: a shared international PINT layer plus a UAE-specific layer, 303 rules in total in version 1.0.2 (28 January 2026). Every rule is explained in plain language in our <a href="/rules">rule library</a>.</li>
<li>UAE-specific data includes the 8-character transaction type code (free zone, deemed supply, margin scheme, summary, continuous supply, agent billing, e-commerce, export), emirate codes (AUH, DXB, SHJ, AJM, UAQ, RAK, FUJ), line amounts in AED, item type with HS or service accounting codes, and credit note reason codes.</li>
</ul>

<h2 id="penalties">Penalties</h2>
<ul>
<li><strong>AED 5,000 per month</strong> (or part of a month) for not implementing e-invoicing or not appointing an ASP on time.</li>
<li><strong>AED 100 per e-invoice</strong> not issued or transmitted to the recipient through the system on time.</li>
<li><strong>AED 1,000 per day</strong> for not notifying the authority promptly of a system failure that prevents e-invoicing.</li>
</ul>
<p>Beyond fines, an invoice outside the system may not support your customer's input VAT claim, so large customers will insist on compliant invoices.</p>

<h2 id="prepare">How to prepare: a practical checklist</h2>
<ol>
<li><strong>Collect TINs.</strong> Your own and every business customer's 10-digit TIN, not just the TRN.</li>
<li><strong>Clean customer master data:</strong> legal name as on the trade licence, TRN, licence number and issuing authority, structured address with emirate code.</li>
<li><strong>Map VAT treatments</strong> in your system to the PINT AE categories: S (standard 5%), Z (zero-rated), E (exempt, with reason code), O (out of scope), AE (reverse charge).</li>
<li><strong>Use proper unit codes</strong> (UN/ECE: H87 piece, KGM kilogram, HUR hour, MTK square metre, XBX box...).</li>
<li><strong>Add payment means, due date and IBAN</strong> to invoices; record the original invoice and reason on every credit note.</li>
<li><strong>Run your real invoices through a readiness check</strong> to see exactly which fields fail. <a href="/">Try it free</a>.</li>
<li><strong>Appoint an ASP</strong> before your deadline and test in the pilot phase.</li>
</ol>

<h2 id="ar" lang="ar" dir="rtl">ملخص بالعربية</h2>
<p lang="ar" dir="rtl">تنتقل دولة الإمارات إلى الفوترة الإلكترونية الإلزامية بين الشركات وللجهات الحكومية. الشركات التي تقل إيراداتها عن 50 مليون درهم يجب أن تعيّن مزود خدمة معتمداً بحلول 31 مارس 2027 وأن تبدأ التطبيق في 1 يوليو 2027. تستخدم الفاتورة الإلكترونية صيغة PINT AE بلغة XML. يمكنك فحص فواتيرك مجاناً على هذا الموقع.</p>
"""


DEADLINES = f"""
<p class="lede">Every key UAE e-invoicing date and penalty on one page, with what each one means for a small or mid-sized business.</p>
<p class="meta">Last reviewed {REVIEWED}. Dates per Ministerial Decision 244 of 2025 as amended by Ministerial Decision 66 of 2026; penalties per Cabinet Decision 106 of 2025. Always confirm on the Ministry of Finance e-invoicing portal.</p>
<h2>Timeline</h2>
<table>
<tr><th>Date</th><th>What happens</th></tr>
<tr><td>1 July 2026</td><td>Voluntary pilot opens to any business</td></tr>
<tr><td>30 October 2026</td><td>Businesses with revenue of AED 50 million or more must have appointed an ASP</td></tr>
<tr><td>1 January 2027</td><td>E-invoicing mandatory for businesses with revenue of AED 50 million or more</td></tr>
<tr><td><strong>31 March 2027</strong></td><td><strong>Businesses with revenue below AED 50 million must have appointed an ASP</strong></td></tr>
<tr><td><strong>1 July 2027</strong></td><td><strong>E-invoicing mandatory for businesses below AED 50 million</strong></td></tr>
<tr><td>1 October 2027</td><td>Government entities go live</td></tr>
</table>
<h2>Penalties</h2>
<table>
<tr><th>Violation</th><th>Penalty</th></tr>
<tr><td>Not implementing the e-invoicing system or not appointing an ASP on time</td><td>AED 5,000 per month or part of a month</td></tr>
<tr><td>Not issuing or transmitting an e-invoice to the recipient on time</td><td>AED 100 per e-invoice</td></tr>
<tr><td>Not notifying the authority promptly of a system failure</td><td>AED 1,000 per day</td></tr>
</table>
<h2>Worked example</h2>
<p>A trading company that sends 300 invoices a month and goes live two months late could face AED 10,000 for the late implementation plus per-invoice penalties for invoices not issued through the system, and its customers may refuse invoices that do not support their own input VAT recovery.</p>
<h2>What to do now</h2>
<ol>
<li>Confirm your revenue band and your two dates (ASP appointment and go-live).</li>
<li><a href="/">Check a sample of your real invoices</a> against the official rules to see the data gaps.</li>
<li>Fix master data (TINs, addresses, VAT categories) before choosing a provider; it shortens onboarding.</li>
</ol>
"""


TIN_TRN = f"""
<p class="lede">The single most common gap in UAE e-invoicing readiness checks: invoices carry the 15-digit TRN but not the 10-digit TIN that the e-invoicing network needs.</p>
<p class="meta">Last reviewed {REVIEWED}.</p>
<table>
<tr><th></th><th>TRN</th><th>TIN</th></tr>
<tr><td>Full name</td><td>Tax Registration Number</td><td>Tax Identification Number</td></tr>
<tr><td>Format</td><td>15 characters, starts with 1, ends with 03 (e.g. 100123456700003)</td><td>10 digits, starts with 1 (e.g. 1001234567)</td></tr>
<tr><td>Who has one</td><td>VAT-registered businesses</td><td>Taxpayers registered with the FTA, including for corporate tax</td></tr>
<tr><td>Role in an e-invoice</td><td>Seller and buyer VAT identifiers on a tax invoice</td><td>Electronic address on the Peppol network: participant ID <code>0235:&lt;TIN&gt;</code></td></tr>
<tr><td>PINT AE rule</td><td><a href="/rules/ibr-132-ae">ibr-132-ae</a> checks the format</td><td><a href="/rules/ibr-148-ae">ibr-148-ae</a> checks the format; <a href="/rules/ibr-080">ibr-080</a> and <a href="/rules/ibr-081">ibr-081</a> require the electronic addresses</td></tr>
</table>
<h2>Why both matter</h2>
<p>The TIN is how an Accredited Service Provider finds your customer on the network; without it the e-invoice cannot be delivered. The TRN proves the VAT status of each party on a tax invoice. A business that is not VAT registered still needs a TIN and can issue an invoice without a TRN in the out-of-scope (type 480) form where applicable.</p>
<h2>Common mistakes we see in real exports</h2>
<ul>
<li>A column called "network ID" or "Peppol ID" that actually contains the 15-digit TRN.</li>
<li>TRNs with spaces or dashes, or exported from Excel in scientific notation (1.00123E+14).</li>
<li>Customer masters with no TIN at all, because it was never needed before.</li>
</ul>
<p><a href="/peppol-tin-lookup">Check whether a TIN is registered on the network</a> or <a href="/">run a readiness check on your customer list</a>.</p>
"""


VALIDATOR = f"""
<p class="lede">Validate a UAE e-invoice XML (UBL 2.1 Invoice or CreditNote) against the UBL schema and the official PINT AE 1.0.2 rule sets, the same artefacts Accredited Service Providers use, and get every failure explained in plain language.</p>
<p><a class="btn primary" href="/#xml">Open the XML validator</a></p>
<h2>What is checked</h2>
<ul>
<li><strong>XML structure:</strong> UBL 2.1 XSD (element order, data types, mandatory structure).</li>
<li><strong>Shared PINT rules:</strong> the international Peppol PINT business rules (totals, VAT breakdown arithmetic, code lists, cardinality).</li>
<li><strong>UAE-specific rules:</strong> the jurisdiction layer for the UAE (TRN and TIN formats, emirate codes, transaction type codes, AED amounts, credit note reasons, item classification).</li>
</ul>
<h2>Who it is for</h2>
<p>ERP and accounting-software developers generating PINT AE, integration teams preparing for ASP onboarding, and consultants reviewing sample invoices. Rule failures link to the <a href="/rules">rule library</a> with the fix for each one.</p>
<h2>Don't have XML yet?</h2>
<p>Most small businesses don't. Upload an Excel or CSV export instead and the <a href="/">readiness check</a> converts it to PINT AE and validates it for you.</p>
"""


LOOKUP = f"""
<p class="lede">Check whether a UAE business can already receive e-invoices: enter its 10-digit TIN and we query the live Peppol network registry (SML) and the Peppol Directory.</p>
<p><a class="btn primary" href="/#lookup">Open the TIN lookup</a></p>
<h2>How it works</h2>
<p>On the Peppol network every receiver is published under a participant identifier. For the UAE that is scheme <code>0235</code> plus the TIN. If the identifier is registered with an Accredited Service Provider's service metadata publisher (SMP), e-invoices addressed to it can be delivered. If it is not registered yet, the business has not completed onboarding.</p>
<h2>What the results mean</h2>
<ul>
<li><strong>Reachable:</strong> registered on the production network; you can send e-invoices to it today.</li>
<li><strong>Test network only:</strong> the provider is still testing.</li>
<li><strong>Not registered yet:</strong> the business or its provider has not published the TIN; plan for a PDF fallback until it does.</li>
</ul>
<p>Not sure which number is the TIN? See <a href="/uae-tin-vs-trn">TIN vs TRN</a>.</p>
"""


PRIVACY = f"""
<p class="meta">Last updated {REVIEWED}.</p>
<h2>Files you upload</h2>
<p>Files are processed in memory to produce your report and are discarded when the request finishes. We do not store invoice files, their contents or their file names.</p>
<h2>What we record when you visit</h2>
<p>Like most websites, our server records technical information about each visit: IP address, browser and device type (user agent), the page requested, the referring page, preferred language, approximate screen size and time zone, and summary counts of tool usage (for example: an Excel file with 34 invoices was checked and 19 rule types failed). We use it to keep the service secure, prevent abuse, and understand which pages are useful. We do not use advertising trackers or third-party analytics, and we do not set cookies.</p>
<h2>If you contact us</h2>
<p>If you choose to send us your email address or WhatsApp number, we use it only to send the report you asked for and to reply to you.</p>
<h2>Retention</h2>
<p>Visit records are kept in our hosting provider's logs for up to 30 days, then deleted automatically.</p>
<h2>Not affiliated</h2>
<p>This site is independent and is not affiliated with the UAE Ministry of Finance, the Federal Tax Authority or OpenPeppol.</p>
"""


PAGES = {
    "/uae-e-invoicing-guide": {
        "title": "UAE E-Invoicing Guide 2026–2027: Deadlines, Scope, PINT AE, ASP & Penalties",
        "h1": "UAE e-invoicing: the complete plain-language guide",
        "description": "What UAE e-invoicing means for your business: who must comply, ASP appointment and go-live deadlines (1 Jan 2027, 1 Jul 2027), the PINT AE format, the five-corner model, penalties and a preparation checklist.",
        "body": GUIDE, "nav": "Guide", "priority": "0.9",
    },
    "/uae-e-invoicing-deadlines-penalties": {
        "title": "UAE E-Invoicing Deadlines & Penalties (2026–2027) — ASP Appointment and Go-Live Dates",
        "h1": "UAE e-invoicing deadlines and penalties",
        "description": "All UAE e-invoicing dates: ASP appointment by 30 Oct 2026 or 31 Mar 2027, go-live 1 Jan 2027 or 1 Jul 2027. Penalties under Cabinet Decision 106 of 2025: AED 5,000 per month, AED 100 per invoice.",
        "body": DEADLINES, "nav": "Deadlines", "priority": "0.8",
    },
    "/uae-tin-vs-trn": {
        "title": "UAE TIN vs TRN for E-Invoicing — 10-digit TIN, 15-digit TRN, Peppol 0235",
        "h1": "TIN vs TRN: which number does a UAE e-invoice need?",
        "description": "The UAE TRN is 15 digits ending in 03; the TIN is 10 digits starting with 1 and is your Peppol e-invoicing address (scheme 0235). Why both appear on a PINT AE e-invoice and the mistakes to avoid.",
        "body": TIN_TRN, "nav": "TIN vs TRN", "priority": "0.8",
    },
    "/pint-ae-validator": {
        "title": "PINT AE Validator — Free UAE E-Invoice XML Validation (UBL 2.1, Peppol)",
        "h1": "PINT AE XML validator",
        "description": "Free online PINT AE validator for UAE e-invoices: UBL 2.1 schema plus the official shared and UAE-specific Schematron rules (PINT AE 1.0.2), with every error explained.",
        "body": VALIDATOR, "nav": "XML validator", "priority": "0.8",
    },
    "/peppol-tin-lookup": {
        "title": "UAE Peppol TIN Lookup — Can This Business Receive E-Invoices?",
        "h1": "UAE Peppol participant lookup (TIN)",
        "description": "Enter a 10-digit UAE TIN to check if the business is registered on the Peppol e-invoicing network (participant 0235:TIN) via the SML and Peppol Directory.",
        "body": LOOKUP, "nav": "TIN lookup", "priority": "0.7",
    },
    "/privacy": {
        "title": "Privacy — UAE Invoice Check",
        "h1": "Privacy",
        "description": "How UAE Invoice Check handles uploaded files (never stored) and visit data.",
        "body": PRIVACY, "nav": None, "priority": "0.2",
    },
}
