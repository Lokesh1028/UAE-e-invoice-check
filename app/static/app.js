(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  $("#year").textContent = new Date().getFullYear();
  try {
    const saved = JSON.parse(localStorage.getItem("sellerProfile") || "{}");
    document.querySelectorAll("#sellerbox [name^=seller_]").forEach((el) => { if (saved[el.name]) el.value = saved[el.name]; });
    if (Object.values(saved).some(Boolean)) $("#sellerbox").open = true;
  } catch (_) {}
  let lastReport = null;
  let lastFile = null;
  let inspectInfo = null;

  // ---------- file drop
  const drop = $("#drop"), fileInput = $("#file"), fname = $("#fname");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; onFile(); } });
  fileInput.addEventListener("change", onFile);

  async function onFile() {
    const f = fileInput.files[0];
    if (!f) return;
    lastFile = f;
    fname.textContent = `${f.name} · ${(f.size / 1024).toFixed(0)} KB`;
    $("#result").classList.add("hidden"); $("#error").classList.add("hidden"); $("#mapping").classList.add("hidden");
    inspectInfo = null;
    if (/\.(xlsx|xlsm|csv|txt)$/i.test(f.name)) {
      try {
        const fd = new FormData(); fd.append("file", f);
        const r = await fetch("/api/inspect", { method: "POST", body: fd });
        if (r.ok) { inspectInfo = await r.json(); renderMapping(inspectInfo); }
      } catch (_) { /* mapping UI is optional */ }
    }
  }

  const FIELD_LABELS = {
    inv_number: "Invoice number *", inv_date: "Invoice date *", due_date: "Due date", doc_type: "Document type (INV/CRN)",
    entity_code: "Seller / entity code", cust_code: "Customer code", cust_name: "Customer name *", cust_trn: "Customer TRN", cust_tin: "Customer TIN",
    currency: "Currency", fx_rate: "Exchange rate to AED", po_number: "PO / order ref", payment_method: "Payment method", payment_terms: "Payment terms", incoterms: "Incoterms",
    orig_invoice: "Original invoice (credit notes)", credit_reason: "Credit note reason", note: "Remarks",
    line_no: "Line no", item_code: "Item code", description: "Description *", nature: "Goods / service", qty: "Quantity *", uom: "Unit", unit_price: "Unit price *",
    gross_price: "List price (before discount)", price_per: "Price per (pack qty)", line_value: "Line net amount", tax_code: "VAT code / treatment", tax_rate: "VAT %",
    tax_amount: "VAT amount", line_total: "Line total incl. VAT", invoice_total: "Invoice total", hs_code: "HS code", sac_code: "SAC code", discount: "Line discount",
  };

  function renderMapping(info) {
    const inv = info.sheets.find((s) => s.role === "invoices");
    const box = $("#mapping");
    if (!inv) {
      box.innerHTML = `<h4>We could not find an invoice sheet automatically</h4><p class="note">Sheets seen: ${info.sheets.map((s) => `<b>${esc(s.name)}</b> (${esc(s.role)}, ${s.rows} rows)`).join(", ")}. Pick the sheet that holds one row per invoice line:</p>
        <select id="sheetpick">${info.sheets.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("")}</select>`;
      box.classList.remove("hidden");
      return;
    }
    const others = info.sheets.filter((s) => s !== inv && s.role !== "unknown").map((s) => `${esc(s.name)} → ${esc(s.role)}`);
    const opts = (sel) => `<option value="">— not in file —</option>` + inv.headers.filter(Boolean).map((h) => `<option value="${esc(h)}" ${h === sel ? "selected" : ""}>${esc(h)}</option>`).join("");
    const important = ["inv_number", "inv_date", "due_date", "cust_name", "cust_trn", "cust_tin", "currency", "description", "qty", "uom", "unit_price", "line_value", "tax_code", "tax_rate", "tax_amount", "payment_method", "doc_type", "orig_invoice"];
    box.innerHTML = `<h4>Detected: sheet “${esc(inv.name)}” with ${inv.rows} rows${others.length ? `, plus ${others.join(", ")}` : ""}</h4>
      <p class="note">Check the column mapping below (we guessed from the headers). Fields marked * are needed for a meaningful check. Change anything that is wrong, then run.</p>
      <div class="grid">${important.map((k) => `<label>${esc(FIELD_LABELS[k] || k)}<select data-field="${k}">${opts(inv.mapping[k] || "")}</select></label>`).join("")}</div>`;
    box.classList.remove("hidden");
  }

  function currentMapping() {
    const m = {};
    document.querySelectorAll("#mapping select[data-field]").forEach((s) => { m[s.dataset.field] = s.value; });
    return Object.keys(m).length ? m : null;
  }

  // ---------- readiness
  $("#form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = fileInput.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const map = currentMapping(); if (map) fd.append("mapping", JSON.stringify(map));
    const sp = $("#sheetpick"); if (sp) fd.append("sheet", sp.value);
    if ($("#showxml").checked) fd.append("include_xml", "true");
    const sellerVals = {};
    document.querySelectorAll("#sellerbox [name^=seller_]").forEach((el) => { if (el.value) { fd.append(el.name, el.value); } sellerVals[el.name] = el.value; });
    try { localStorage.setItem("sellerProfile", JSON.stringify(sellerVals)); } catch (_) {}
    $("#run").disabled = true; $("#progress").classList.remove("hidden"); $("#error").classList.add("hidden"); $("#result").classList.add("hidden");
    try {
      const r = await fetch("/api/readiness", { method: "POST", body: fd });
      const data = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      lastReport = data;
      renderReport(data);
    } catch (err) {
      $("#error").textContent = err.message || String(err); $("#error").classList.remove("hidden");
    } finally {
      $("#run").disabled = false; $("#progress").classList.add("hidden");
    }
  });

  function renderReport(d) {
    const s = d.summary, docs = s.documents || 0, ready = s.documents_ready || 0;
    const pct = docs ? Math.round((ready / docs) * 100) : 0;
    const cls = pct === 100 ? "good" : pct >= 50 ? "mid" : "bad";
    const src = d.source || {};
    const srcLine = src.kind === "pdf" ? `PDF invoice · ${src.pdf?.lines_found || 0} line items read` : src.kind === "xml" ? `Uploaded XML (${esc(src.doc_type || "unknown type")})` : `Sheet “${esc(src.invoice_sheet || "")}” · ${src.rows_read || 0} rows${(src.masters_used || []).length ? ` · joined: ${src.masters_used.join(", ")}` : ""}`;
    let html = `
      <div class="score"><div class="pct ${cls}">${pct}%</div>
        <div><p><b>${ready} of ${docs}</b> document${docs === 1 ? "" : "s"} would pass the official UAE PINT AE rules as they are.</p>
        <p><small>${srcLine} · ${s.fatal_total} blocking error${s.fatal_total === 1 ? "" : "s"} across ${s.distinct_rules} rule${s.distinct_rules === 1 ? "" : "s"} · ${s.processing_ms} ms</small></p></div></div>
      <div class="actions">
        <button class="btn primary" id="dl">Download PDF report</button>
        <a class="btn ghost" href="#cta">Email me this report</a>
        ${d.sample_xml ? `<button class="btn ghost" id="showxmlbtn">Show generated XML</button>` : ""}
      </div>`;
    if (src.kind !== "pdf" && src.kind !== "xml" && !(src.masters_used || []).includes("entities") && !src.seller_profile_used) html += `<p class="note"><b>Tip:</b> this export has no seller/entity sheet, so every document is missing your own company's TIN, TRN, licence and address. Fill in “Your company details” above and re-run to see only the real gaps.</p>`;
    if ((src.unmapped_headers || []).length) html += `<p class="note">Columns we did not use: ${src.unmapped_headers.map(esc).join(", ")}. If one of them holds a required field, map it above and re-run.</p>`;
    if (src.kind === "pdf") html += `<p class="note">Read from the PDF: number ${esc(src.pdf?.extracted?.number || "—")}, date ${esc(src.pdf?.extracted?.date || "—")}, seller ${esc(src.pdf?.extracted?.seller || "—")} (TRN ${esc(src.pdf?.extracted?.seller_trn || "—")}), buyer ${esc(src.pdf?.extracted?.buyer || "—")} (TRN ${esc(src.pdf?.extracted?.buyer_trn || "—")}), total ${esc(src.pdf?.extracted?.total || "—")}. PDF reading is best-effort; an Excel/CSV export gives a more complete picture.</p>`;
    html += `<h3 style="margin:18px 0 4px;color:var(--navy)">What to fix, in order of impact</h3>`;
    if (!d.issues.length) html += `<p class="note">No rule failures. These documents are ready in their current form.</p>`;
    d.issues.slice(0, 40).forEach((it, i) => {
      html += `<div class="issue"><div class="t"><h4><span class="sev ${esc(it.severity)}">${it.severity === "fatal" ? "Blocking" : "Warning"}</span>${i + 1}. ${esc(it.title)}</h4><span class="n">${it.documents} doc${it.documents === 1 ? "" : "s"} · ${it.count} occurrence${it.count === 1 ? "" : "s"}</span></div>
        <p>${esc(it.plain)}</p>${it.fix ? `<p class="fix"><b>Fix:</b> ${esc(it.fix)}</p>` : ""}
        <div class="meta">Rule ${esc(it.rule_id)} · ${esc(it.layer_label)}${it.field ? ` · field: ${esc(it.field)}` : ""}${it.example ? ` · e.g. ${esc(it.example)}` : ""}</div></div>`;
    });
    if (d.documents && d.documents.length > 1) {
      html += `<h3 style="margin:18px 0 4px;color:var(--navy)">Document by document</h3><table class="docs"><tr><th>Number</th><th>Date</th><th>Customer</th><th>Errors</th><th>Details</th></tr>`;
      d.documents.forEach((doc) => {
        const list = doc.findings.map((f) => `<li><b>${esc(f.title)}</b> <span class="note">(${esc(f.rule_id)})</span>${f.location ? "" : ""}</li>`).join("");
        html += `<tr class="${doc.fatal ? "bad" : "ok"}"><td>${esc(doc.number || "")}${doc.doc_type === "creditnote" ? " <span class='note'>(credit note)</span>" : ""}</td><td>${esc(doc.date || "")}</td><td>${esc(doc.buyer || "")}</td><td>${doc.fatal}</td><td>${doc.fatal ? `<details><summary>${doc.findings.length} finding${doc.findings.length === 1 ? "" : "s"}</summary><ul>${list}</ul></details>` : "Ready"}</td></tr>`;
      });
      html += `</table>`;
      if (s.truncated) html += `<p class="note">Showing the first ${d.documents.length} documents.</p>`;
    } else if (d.documents && d.documents.length === 1 && d.documents[0].findings.length) {
      html += `<h3 style="margin:18px 0 4px;color:var(--navy)">All findings</h3><ul>${d.documents[0].findings.map((f) => `<li><span class="sev ${esc(f.severity)}">${f.severity}</span><b>${esc(f.title)}</b> — ${esc(f.plain)} <span class="note">(${esc(f.rule_id)}${f.location ? ` · ${esc(f.location.replace(/\[namespace-uri\(\)=[^\]]+\]/g, "").slice(0, 90))}` : ""})</span></li>`).join("")}</ul>`;
    }
    if (d.sample_xml) html += `<pre class="xml hidden" id="xmlpre">${esc(d.sample_xml)}</pre>`;
    const box = $("#result"); box.innerHTML = html; box.classList.remove("hidden");
    $("#dl").addEventListener("click", downloadPdf);
    const sx = $("#showxmlbtn"); if (sx) sx.addEventListener("click", () => $("#xmlpre").classList.toggle("hidden"));
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function downloadPdf() {
    if (!lastReport) return;
    const btn = $("#dl"); btn.disabled = true; btn.textContent = "Preparing PDF…";
    try {
      const r = await fetch("/api/report.pdf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...lastReport, sample_xml: undefined, source: { ...lastReport.source, filename: lastFile ? lastFile.name : lastReport.source.filename } }) });
      if (!r.ok) throw new Error("PDF failed");
      const blob = await r.blob(); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "einvoice-readiness-report.pdf"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) { alert("Could not build the PDF. Please try again."); }
    finally { btn.disabled = false; btn.textContent = "Download PDF report"; }
  }

  // ---------- XML validator
  $("#xmlfile").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) $("#xmltext").value = await f.text(); });
  $("#xmlsample").addEventListener("click", async () => { const r = await fetch("/static/sample-invoice.xml"); $("#xmltext").value = await r.text(); });
  $("#xmlform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const xml = $("#xmltext").value.trim(); if (!xml) return;
    const box = $("#xmlresult"); box.innerHTML = `<div class="progress"><div class="bar"></div><span>Validating…</span></div>`; box.classList.remove("hidden");
    try {
      const r = await fetch("/api/validate-xml", { method: "POST", headers: { "Content-Type": "application/xml" }, body: xml });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      let html = `<div class="score"><div class="pct ${d.valid ? "good" : "bad"}">${d.valid ? "PASS" : "FAIL"}</div><div><p><b>${esc(d.doc_type || "unknown")}</b> · XSD ${d.xsd_valid ? "valid" : "invalid"} · ${d.fatal} fatal · ${d.warnings} warning${d.warnings === 1 ? "" : "s"} · ${d.timing_ms} ms</p><p><small>${esc(d.rule_set)}</small></p></div></div>`;
      if (d.findings.length) html += `<ul>` + d.findings.map((f) => `<li><span class="sev ${esc(f.severity)}">${esc(f.severity)}</span><b>${esc(f.title)}</b> — ${esc(f.plain)}<div class="note">${esc(f.rule_id)} · ${esc(f.layer_label)}${f.location ? ` · ${esc(f.location.replace(/\[namespace-uri\(\)=[^\]]+\]/g, "").slice(0, 120))}` : ""}<br><i>${esc(f.message)}</i></div></li>`).join("") + `</ul>`;
      box.innerHTML = html;
    } catch (err) { box.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
  });

  // ---------- lookup
  $("#lookupform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const tin = $("#tin").value.replace(/\s/g, "");
    const box = $("#lookupresult"); box.innerHTML = `<div class="progress"><div class="bar"></div><span>Querying the Peppol network…</span></div>`; box.classList.remove("hidden");
    try {
      const r = await fetch(`/api/lookup/${encodeURIComponent(tin)}`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const label = { reachable: "Reachable on the live network", "test-only": "Registered on the TEST network only", "not-found": "Not registered yet", invalid: "Not a valid TIN", unknown: "Could not determine" }[d.verdict] || d.verdict;
      box.innerHTML = `<div class="verdict ${esc(d.verdict)}"><b>${esc(label)}</b>${esc(d.explanation)}${d.directory_name ? `<div class="note">Peppol Directory name: ${esc(d.directory_name)}</div>` : ""}<div class="note">Participant ID ${esc(d.participant_id)}${d.smp_host && d.smp_host !== "found" ? ` · provider endpoint ${esc(d.smp_host)}` : ""}</div></div>`;
    } catch (err) { box.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
  });

  // ---------- lead
  $("#leadform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { email: $("#lead_email").value, whatsapp: $("#lead_whatsapp").value, company: $("#lead_company").value, summary: lastReport ? lastReport.summary : {}, source: lastReport ? (lastReport.source.kind || "") : "none" };
    const out = $("#leadresult");
    try {
      const r = await fetch("/api/lead", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed");
      out.textContent = "Thanks. We will send the report and get back to you within one working day.";
      if (lastReport) downloadPdf();
    } catch (err) { out.textContent = err.message; }
  });
})();
