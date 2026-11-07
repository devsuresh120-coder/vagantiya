"""Small Facebook Graph API helper for the වගන්තිය (Vagantiya) Page.

Env (GitHub secrets): FB_PAGE_ID, FB_PAGE_TOKEN (a Page token made from a long-lived user token: never expires).
The token is never printed or written anywhere.
"""
import os, sys, time, json
import requests

GRAPH = "https://graph.facebook.com/v26.0"


def creds():
    pid, tok = os.environ.get("FB_PAGE_ID", "").strip(), os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not pid or not tok:
        sys.exit("missing secret FB_PAGE_ID or FB_PAGE_TOKEN")
    return pid, tok


def _clean(msg):
    tok = os.environ.get("FB_PAGE_TOKEN", "")
    return msg.replace(tok, "***") if tok else msg


class FBError(Exception):
    pass


def call(method, path, **params):
    _, tok = creds()
    params["access_token"] = tok
    for attempt in range(3):
        r = requests.request(method, f"{GRAPH}/{path.lstrip('/')}", data=params if method != "GET" else None,
                             params=params if method == "GET" else None, timeout=120)
        if r.status_code in (500, 502, 503) and attempt < 2:
            time.sleep(5 * (attempt + 1)); continue
        break
    try:
        j = r.json()
    except Exception:
        raise FBError(_clean(f"HTTP {r.status_code}: {r.text[:300]}"))
    if "error" in j:
        e = j["error"]
        raise FBError(_clean(f"{e.get('type')} {e.get('code')}/{e.get('error_subcode')}: {e.get('message')}"))
    return j


# ---------- albums ("folders": one Page album per topic) ----------

def album_create(name, message):
    pid, _ = creds()
    return call("POST", f"{pid}/albums", name=name, message=message)["id"]


def album_add(album_id, url, caption=""):
    """Copy an image into the album without a new feed story (the feed post already exists)."""
    return call("POST", f"{album_id}/photos", url=url, caption=caption, no_story="true")["id"]


# ---------- posts ----------

def photo_post(urls, message, scheduled_ts=None):
    """One image or an album (several images in one post). scheduled_ts = unix time (10 min – 30 days ahead) or None = now."""
    pid, _ = creds()
    sched = {"published": "false", "scheduled_publish_time": str(int(scheduled_ts))} if scheduled_ts else {}
    # one image or many: always photos uploaded unpublished + one feed post, so every post is a normal Page post
    # (a bare /photos upload showed under Photos but not reliably in the Page's posts for other viewers)
    media = []
    for u in urls:
        j = call("POST", f"{pid}/photos", url=u, published="false", temporary="true" if scheduled_ts else "false")
        media.append({"media_fbid": j["id"]})
    j = call("POST", f"{pid}/feed", message=message, attached_media=json.dumps(media), **sched)
    return j["id"]


def reel_post(video_url, description, scheduled_ts=None, draft=False):
    """Facebook Reel from a public video URL (3 steps: start, upload by URL, finish)."""
    pid, tok = creds()
    start = call("POST", f"{pid}/video_reels", upload_phase="start")
    vid, upload_url = start["video_id"], start["upload_url"]
    r = requests.post(upload_url, headers={"Authorization": f"OAuth {tok}", "file_url": video_url}, timeout=300)
    if r.status_code >= 300:
        raise FBError(_clean(f"reel upload HTTP {r.status_code}: {r.text[:300]}"))
    fin = {"upload_phase": "finish", "video_id": vid, "description": description}
    if draft:
        fin["video_state"] = "DRAFT"
    elif scheduled_ts:
        fin.update(video_state="SCHEDULED", scheduled_publish_time=str(int(scheduled_ts)))
    else:
        fin["video_state"] = "PUBLISHED"
    call("POST", f"{pid}/video_reels", **fin)
    return vid


def is_published(object_id):
    """Feed posts have is_published; a Reel is a video node, which has 'published' (and a publishing status) instead."""
    try:
        if "_" in object_id:
            return bool(call("GET", object_id, fields="is_published").get("is_published", True))
        j = call("GET", object_id, fields="published,status")
        phase = ((j.get("status") or {}).get("publishing_phase") or {}).get("status")
        return bool(j.get("published")) or phase == "complete" and (j.get("status") or {}).get("publishing_phase", {}).get("publish_status") == "published"
    except FBError:
        return False


def comment(object_id, text):
    return call("POST", f"{object_id}/comments", message=text)["id"]
