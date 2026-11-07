"""Look at official pages/PDFs from the GitHub runner (the chat workspace can't reach gov.lk).

queue/probe_request.json: {"name": "...", "pages": ["https://... js page"], "pdfs": [{"url": ..., "find": ["text", ...], "render": [page numbers]}]}
Writes probe/<name>/: links.txt (hrefs + api calls seen on the js pages), <n>.txt (pdf text per page, first 40 pages),
p<n>.png (rendered pages, and pages where a 'find' text is) — pushed to branch probe/<name>, never main."""
import json, os, re, urllib.request
import fitz

req = json.load(open("queue/probe_request.json"))
out = f"probe/{req['name']}"; os.makedirs(out, exist_ok=True)
log = open(f"{out}/links.txt", "w")
if req.get("pages") or req.get("clicks"):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.on("request", lambda r: log.write("REQ " + r.url + "\n") if "/api/" in r.url else None)
        for u in req.get("pages", []):
            log.write(f"== {u}\n")
            try:
                pg.goto(u, wait_until="networkidle", timeout=90000); pg.wait_for_timeout(4000)
                for a in pg.eval_on_selector_all("a", "els => els.map(e => (e.innerText||'').trim().slice(0,80) + ' | ' + e.href)"):
                    log.write("A " + a + "\n")
                log.write(pg.inner_text("body")[:6000] + "\n")
            except Exception as e:
                log.write(f"ERR {e}\n")
        for c in req.get("clicks", []):   # {"page", "row_text", "buttons": [...]}: click buttons in a table row, log what opens
            log.write(f"== CLICK {c}\n")
            pg.context.on("request", lambda r: log.write("REQ* " + r.url + "\n") if ("content-file" in r.url or ".pdf" in r.url) else None)
            pg.context.on("page", lambda np: log.write("POPUP " + np.url + "\n"))
            pg.goto(c["page"], wait_until="networkidle", timeout=90000); pg.wait_for_timeout(3000)
            for st in c.get("steps", []):   # {"select": n, "label": "1995"} | {"click": "Search"}
                try:
                    if "select" in st:
                        sel = pg.locator("select").nth(st["select"])
                        if sel.count():
                            sel.select_option(label=st["label"])
                        else:   # custom dropdown: click the n-th button then the option text
                            pg.locator("button[aria-haspopup]").nth(st["select"]).click(); pg.wait_for_timeout(800)
                            pg.get_by_role("option", name=st["label"]).first.click()
                    if "fill" in st:
                        pg.get_by_label(st["fill"]).first.fill(st["text"])
                    if "click" in st:
                        pg.get_by_text(st["click"], exact=True).first.click()
                    pg.wait_for_timeout(2500)
                except Exception as e:
                    log.write(f"ERR step {st} {e}\n")
            log.write("BTNS " + " | ".join((b.get_attribute("aria-label") or "") + ":" + (b.inner_text() or "")[:20] for b in pg.locator("button, input, [role=button], nav a, li a").all()[:80]) + "\n")
            log.write("ROWS " + " || ".join(t.strip().replace("\n", " ")[:120] for t in pg.locator("tr").all_inner_texts()) + "\n")
            row = pg.locator("tr", has_text=c["row_text"]).first
            for _ in range(10):   # page through the table until the row shows
                if row.count():
                    break
                try:
                    nxt = pg.locator("[aria-label*='next' i]").first
                    nxt.click(timeout=4000); pg.wait_for_timeout(2500)
                    log.write("PAGE " + " || ".join(t.strip().replace("\n", " ")[:60] for t in pg.locator("tr").all_inner_texts()[2:4]) + "\n")
                except Exception as e:
                    log.write(f"ERR next {e}\n"[:300]); break
            try:
                log.write("ROWHTML " + row.inner_html(timeout=5000)[:3000] + "\n")
            except Exception as e:
                log.write(f"ERR no row '{c['row_text']}'\n"); continue
            for btn in c["buttons"]:
                try:
                    row.get_by_text(btn).first.click()
                except Exception as e:
                    log.write(f"ERR click {btn} {e}\n")
                pg.wait_for_timeout(12000)
                for q in pg.context.pages:
                    log.write(f"PAGE after {btn}: " + q.url + "\n")
        b.close()
for i, d in enumerate(req.get("pdfs", [])):
    log.write(f"== PDF {i} {d['url']}\n")
    try:
        data = urllib.request.urlopen(urllib.request.Request(d["url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
        doc = fitz.open(stream=data, filetype="pdf")
        log.write(f"pages {len(doc)}\n")
        render = set(d.get("render", []))
        for page in doc:
            n = page.number + 1
            t = page.get_text()
            if n <= 40:
                open(f"{out}/{i}_{n}.txt", "w").write(t)
            for f in d.get("find", []):
                if page.search_for(f):
                    log.write(f"FOUND '{f}' on page {n}\n"); render.add(n)
        for n in sorted(render):
            if 1 <= n <= len(doc):
                doc[n - 1].get_pixmap(matrix=fitz.Matrix(2, 2)).save(f"{out}/{i}_p{n}.png")
                json.dump([[round(v, 1) for v in b[:4]] + [b[4][:60]] for b in doc[n - 1].get_text("blocks")],
                          open(f"{out}/{i}_p{n}_blocks.json", "w"), ensure_ascii=False, indent=0)
    except Exception as e:
        log.write(f"ERR {e}\n")
log.close()
