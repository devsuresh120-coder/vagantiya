"""Cut a clause out of an official PDF as a picture (for the 'ඇත්තද?' cards).

queue/clip_request.json: {"url": ..., "start": "text where the cut begins", "end": "text where it ends (not included)",
                          "name": "002_clause"}
Writes clips/<name>.png (3x zoom, full text width) and clips/<name>.txt (the words found), pushed to the branch
clip/<name> by the workflow, never to main."""
import json, os, sys, urllib.request
import fitz  # PyMuPDF

req = json.load(open("queue/clip_request.json"))
data = urllib.request.urlopen(urllib.request.Request(req["url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read()
doc = fitz.open(stream=data, filetype="pdf")
os.makedirs("clips", exist_ok=True)
if req.get("parts"):   # several cuts: [{"page", "rect"}] -> clips/<name>_<k>.png
    txt = ""
    for k, part in enumerate(req["parts"]):
        page = doc[part["page"] - 1]; rect = fitz.Rect(*part["rect"])
        page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=rect).save(f"clips/{req['name']}_{k}.png")
        txt += f"--- part {k} page {part['page']}\n" + page.get_textbox(rect) + "\n"
    open(f"clips/{req['name']}.txt", "w").write(txt)
    sys.exit(0)
if req.get("rect"):   # {"page": n (1-based), "rect": [x0, y0, x1, y1] in PDF points} when the text can't be searched (Sinhala fonts)
    page = doc[req["page"] - 1]; rect = fitz.Rect(*req["rect"])
    page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect).save(f"clips/{req['name']}.png")
    open(f"clips/{req['name']}.txt", "w").write(f"page {req['page']}\n" + page.get_textbox(rect))
    sys.exit(0)
for page in doc:
    s = page.search_for(req["start"])
    if not s:
        continue
    top = s[0].y0 - 6
    e = page.search_for(req["end"]) if req.get("end") else []
    e = [r for r in e if r.y0 > top]
    bottom = (e[0].y0 - 2) if e else top + 160
    blocks = [b for b in page.get_text("blocks") if b[1] < bottom and b[3] > top]
    x0 = min(b[0] for b in blocks) - 8; x1 = max(b[2] for b in blocks) + 8
    rect = fitz.Rect(x0, top, x1, bottom)
    page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect).save(f"clips/{req['name']}.png")
    open(f"clips/{req['name']}.txt", "w").write(f"page {page.number + 1}\n" + page.get_textbox(rect))
    print("cut from page", page.number + 1, rect)
    break
else:
    sys.exit(f"'{req['start']}' not found")
