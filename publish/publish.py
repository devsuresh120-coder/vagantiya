"""වගන්තිය (Vagantiya) publisher: GitHub Actions → Facebook Graph API (no Buffer).

queue/schedule.csv  episode,file,platform,due_at,title,text,comment   (due_at = Sri Lanka time "YYYY-MM-DD HH:MM")
  platform  facebook       image post; file = one r2:<folder>/<file> or several joined with "|" (album, in order)
            facebook-reel  Reel; file = r2:<folder>/<file>.mp4
  text      the caption (\\n = new line). Must carry the source name (rule: every post has its official source).
  comment   first comment (full source links). Added by this script as soon as the post is live.

How it works (every run):
  1. Rows not yet in posted.json whose due_at is 15 min – 29 days ahead → created on Facebook as SCHEDULED posts
     (Facebook publishes them at the exact time). Rows already due (≤ 15 min ahead or past, up to 2 days late) → posted now.
  2. Posts that are live and have a comment but no comment_id yet → the first comment is added.
  posted.json "<episode>:<platform>" → {post_id, due_at, scheduled, comment_id, error, via:"graph"}.
Never marks anything as AI-generated. The Page token is never printed.
Env: FB_PAGE_ID, FB_PAGE_TOKEN. Optional DRY_RUN=1.
"""
import re, requests
import csv, json, os, sys, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
import fb

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCHEDULE, POSTED, R2 = (os.path.join(ROOT, "queue", n) for n in ("schedule.csv", "posted.json", "r2.json"))
TZ = ZoneInfo("Asia/Colombo")
DRY = os.environ.get("DRY_RUN") == "1"
MIN_AHEAD = dt.timedelta(minutes=15)
MAX_AHEAD = dt.timedelta(days=29)
MAX_LATE = dt.timedelta(days=2)


def load(p, default):
    return json.load(open(p)) if os.path.exists(p) else default


def url_of(ref, r2):
    ref = ref.strip()
    if ref.startswith("http"):
        return ref
    if ref not in r2:
        raise fb.FBError(f"{ref} is not on R2 yet (not in queue/r2.json)")
    return r2[ref]["url"]


LINK_RE = re.compile(r"https?://[^\s<>()\"']+")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"}


def broken_links(*texts):
    """Every link in the caption/comment must open (owner, 2026-10-31: a dead source link costs trust)."""
    bad = []
    for u in sorted({m.rstrip(".,;") for t in texts for m in LINK_RE.findall(t or "")}):
        if u.startswith(("https://www.facebook.com/", "https://facebook.com/")):
            continue   # our own posts (filled in from posted.json only once live); Facebook shows bots a login wall
        try:
            r = requests.get(u, headers=UA, timeout=40, stream=True, allow_redirects=True)
            ok = r.status_code < 400 and len(next(r.iter_content(2048), b"")) > 200
            r.close()
        except Exception:
            ok = False
        if not ok:
            bad.append(u)
    return bad


POST_RE = re.compile(r"\{\{post:([^}]+)\}\}")
SERIES_RE = re.compile(r"\{\{series:([^}]+)\}\}")


def permalink(rec):
    pid = rec["post_id"]
    if "_" in pid:
        page, post = pid.split("_", 1)
        return f"https://www.facebook.com/{page}/posts/{post}"
    return f"https://www.facebook.com/reel/{pid}"


def is_live(rec, now):
    if not rec or rec.get("error") or not rec.get("post_id"):
        return False
    due = dt.datetime.strptime(rec["due_at"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ).astimezone(dt.timezone.utc)
    return due <= now and (not rec.get("scheduled") or fb.is_published(rec["post_id"]))


def fill(text, posted, now, series):
    """{{post:<episode>:<platform>}} -> that post's Facebook link (missing until it is live);
    {{series:<slug>}} -> the topic's part list from queue/series.json (live parts linked, the rest 'ළඟදීම').
    Returns (text, missing keys)."""
    missing = []
    def post(m):
        rec = posted.get(m.group(1).strip())
        if not is_live(rec, now):
            missing.append(m.group(1)); return m.group(0)
        return permalink(rec)
    def ser(m):
        s = series.get(m.group(1).strip(), {})
        lines = []
        for label, key in s.get("parts", []):
            rec = posted.get(key)
            lines.append(f"▪️ {label}: " + (permalink(rec) if is_live(rec, now) else "ළඟදීම"))
        return "\n".join(lines)
    text = SERIES_RE.sub(ser, text)
    return POST_RE.sub(post, text), missing


def fingerprint(row):
    import hashlib
    return hashlib.sha1("\x1f".join(row.get(k, "").strip() for k in ("file", "due_at", "text", "comment")).encode()).hexdigest()[:12]


REVIEW = os.path.join(os.path.dirname(POSTED), "review.json")


def approved(row, review):
    """The owner approved this row on the dashboard, for its current file (a re-made post needs a new approval)."""
    rv = review.get(f"{row['episode'].strip()}:{row['platform'].strip()}") or {}
    return rv.get("status") == "approved" and rv.get("file", "") == row["file"].strip()


def main():
    posted, r2 = load(POSTED, {}), load(R2, {})
    review = load(REVIEW, {})
    # queue/redo.txt: one "<episode>:<platform>" per line → delete that Facebook post and create it again
    # (used once when the app went from Development to Live: posts made in Development mode are invisible to the public)
    redo = os.path.join(os.path.dirname(POSTED), "redo.txt")
    redo_done = False
    if os.path.exists(redo) and not DRY:
        for k in [l.strip() for l in open(redo) if l.strip()]:
            rec = posted.get(k)
            if not rec:
                continue
            try:
                fb.call("DELETE", rec["post_id"]); print(f"redo {k}: deleted {rec['post_id']}")
            except fb.FBError as e:
                print(f"::warning title=redo {k}::{str(e)[:200]}")
            posted.pop(k, None)
        os.remove(redo); redo_done = True
    rows = list(csv.DictReader(open(SCHEDULE, encoding="utf-8")))
    series = load(os.path.join(ROOT, "queue", "series.json"), {})
    now = dt.datetime.now(dt.timezone.utc)
    changed = redo_done

    for row in rows:
        key = f"{row['episode'].strip()}:{row['platform'].strip()}"
        if not approved(row, review):
            print(f"waiting {key}: not approved on the dashboard yet"); continue
        rec = posted.get(key)
        if rec and not rec.get("error"):
            fp = fingerprint(row)
            if not rec.get("fp"):
                rec["fp"] = fp; changed = True; continue
            if rec["fp"] == fp:
                continue
            # the row changed after it was sent: re-create it, but only while Facebook still holds it unpublished
            if rec.get("scheduled") and rec.get("post_id") and not fb.is_published(rec["post_id"]) and not DRY:
                try:
                    fb.call("DELETE", rec["post_id"])
                    print(f"changed {key}: deleted the scheduled post, re-creating it")
                    posted.pop(key); changed = True
                except fb.FBError as e:
                    print(f"::warning title=Could not replace {key}::{str(e)[:300]}"); continue
            else:
                print(f"::warning title=Changed after posting {key}::already live on Facebook; edit it there by hand"); continue
        if not row.get("due_at", "").strip():
            print(f"skip {key}: no due_at"); continue
        due = dt.datetime.strptime(row["due_at"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=TZ).astimezone(dt.timezone.utc)
        ahead = due - now
        if ahead > MAX_AHEAD:
            print(f"later {key}: due {row['due_at']}"); continue
        if -ahead > MAX_LATE:
            print(f"::warning title=Missed {key}::due {row['due_at']} is more than 2 days ago; not posted"); continue
        when = int(due.timestamp()) if ahead > MIN_AHEAD else None
        text, missing = fill(row["text"].replace("\\n", "\n").strip(), posted, now, series)
        if missing:
            print(f"waiting {key}: refers to posts not live yet {missing}"); continue
        try:
            urls = [url_of(f, r2) for f in row["file"].split("|") if f.strip()]
            bad = broken_links(text, row.get("comment", "").replace("\\n", "\n"))
            if bad:
                raise fb.FBError("link not opening (fix the link, post waits): " + " ".join(bad))
            if DRY:
                print(f"DRY {key}: {'scheduled' if when else 'now'} {len(urls)} file(s)"); continue
            if row["platform"].strip() == "facebook-reel":
                pid = fb.reel_post(urls[0], text, when)
            else:
                pid = fb.photo_post(urls, text, when)
            posted[key] = {"post_id": pid, "due_at": row["due_at"].strip(), "scheduled": bool(when), "via": "graph", "fp": fingerprint(row), "text_sent": text,
                           "created": now.strftime("%Y-%m-%d %H:%M UTC")}
            print(f"{'scheduled' if when else 'posted'} {key} → {pid}")
        except fb.FBError as e:
            prev = posted.get(key, {})
            posted[key] = {**prev, "error": str(e)[:300], "due_at": row["due_at"].strip(), "via": "graph"}
            print(f"::error title=Facebook refused {key}::{str(e)[:500]}")
        changed = True

    by_key = {f"{r['episode'].strip()}:{r['platform'].strip()}": r for r in rows}
    for key, v in posted.items():
        row = by_key.get(key)
        if not row or not row.get("comment", "").strip() or v.get("comment_id") or v.get("error") or not v.get("post_id"):
            continue
        due = dt.datetime.strptime(v["due_at"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ).astimezone(dt.timezone.utc)
        if due > now or (v.get("scheduled") and not fb.is_published(v["post_id"])):
            continue
        if DRY:
            print(f"DRY comment {key}"); continue
        ctext, missing = fill(row["comment"].replace("\\n", "\n").strip(), posted, now, series)
        if missing:
            print(f"comment {key} waits for {missing}"); continue
        try:
            v["comment_id"] = fb.comment(v["post_id"], ctext)
            v.pop("comment_error", None)
            print(f"first comment added on {key}")
        except fb.FBError as e:
            v["comment_error"] = str(e)[:300]
            print(f"::warning title=First comment failed on {key}::{str(e)[:500]}")
        changed = True

    # A caption with {{series:..}} (the topic's part list) is edited on Facebook whenever a new part goes live.
    for key, v in posted.items():
        row = by_key.get(key)
        if not row or "{{series:" not in row.get("text", "") or DRY or not is_live(v, now):
            continue
        text, _ = fill(row["text"].replace("\\n", "\n").strip(), posted, now, series)
        if text != v.get("text_sent"):
            try:
                fb.call("POST", v["post_id"], message=text); v["text_sent"] = text; v.pop("edit_error", None)
                print(f"{key}: part list updated")
            except fb.FBError as e:
                v["edit_error"] = str(e)[:300]; print(f"::warning title=Part list edit failed {key}::{str(e)[:300]}")
            changed = True

    # queue/albums.json: topic albums ("folders"). A post's images are copied into its album only once it is live,
    # so nothing shows in the album before the post time.
    albums_path = os.path.join(ROOT, "queue", "albums.json")
    albums = load(albums_path, {})
    albums_changed = False
    for slug, al in albums.items():
        if not al.get("id"):   # the Graph API can't create Page albums (#3); the owner makes it once on Facebook, its id goes here
            continue
        for key in al.get("rows", []):
            v, row = posted.get(key), by_key.get(key)
            if not v or not row or v.get("error") or not v.get("post_id") or v.get("album_photos") or DRY:
                continue
            due = dt.datetime.strptime(v["due_at"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ).astimezone(dt.timezone.utc)
            if due > now or (v.get("scheduled") and not fb.is_published(v["post_id"])):
                continue
            try:
                caption = (row.get("title") or "").strip()
                v["album_photos"] = [fb.album_add(al["id"], url_of(f, r2), caption) for f in row["file"].split("|") if f.strip()]
                v["album"] = slug; v.pop("album_error", None)
                print(f"{key}: {len(v['album_photos'])} image(s) copied into album {slug}")
            except fb.FBError as e:
                v["album_error"] = str(e)[:300]
                print(f"::warning title=Album {slug} failed for {key}::{str(e)[:500]}")
            changed = True
    if albums_changed:
        json.dump(albums, open(albums_path, "w"), indent=1, ensure_ascii=False)

    if changed and not DRY:
        json.dump(posted, open(POSTED, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
