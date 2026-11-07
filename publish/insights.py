"""Read-only Facebook stats for the වගන්තිය Page. Posts NOTHING.

Writes queue/insights.json: Page totals + one record per post we published (from queue/posted.json),
so the weekly review can see what works. Metric names change between Graph API versions, so every
metric is tried on its own and a failure is recorded instead of stopping the run."""
import os, json, csv, datetime as dt
from fb import call, creds, FBError

HERE = os.path.dirname(os.path.abspath(__file__))
Q = os.path.join(HERE, "..", "queue")

PAGE_METRICS = ["page_follows", "page_daily_follows_unique", "page_views_total", "page_impressions_unique",
                "page_post_engagements", "page_media_view", "page_total_media_view_unique"]
POST_METRICS = ["post_impressions_unique", "post_media_view", "post_total_media_view_unique",
                "post_clicks", "post_reactions_by_type_total", "post_engaged_users"]
REEL_METRICS = ["blue_reels_play_count", "fb_reels_total_plays", "fb_reels_replay_count", "post_video_avg_time_watched",
                "post_video_view_time", "post_impressions_unique", "post_video_followers", "post_video_social_actions"]


def metric(obj, name, period=None):
    try:
        kw = {"metric": name}
        if period:
            kw["period"] = period
        data = call("GET", f"{obj}/insights", **kw).get("data", [])
        if not data:
            return None
        vals = data[0].get("values") or []
        if period == "day":
            return [{"end": v.get("end_time", "")[:10], "value": v.get("value")} for v in vals]
        return vals[-1].get("value") if vals else None
    except FBError as e:
        return {"error": str(e)[:120]}


def reel_metrics(video_id, feed_post_id=None):
    """Reels: the video object has a video_insights edge (not insights); the feed post may also give post metrics."""
    out = {}
    try:
        for x in call("GET", f"{video_id}/video_insights").get("data", []):
            vals = x.get("values") or []
            out[x.get("name")] = vals[-1].get("value") if vals else None
    except FBError as e:
        out["video_insights_error"] = str(e)[:120]
    if feed_post_id:
        pid, _ = creds()
        fid = feed_post_id if "_" in str(feed_post_id) else f"{pid}_{feed_post_id}"
        for m in ("post_media_view", "post_total_media_view_unique", "post_clicks"):
            out[m] = metric(fid, m)
    return out


def main():
    pid, _ = creds()
    out = {"fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    page = call("GET", pid, fields="name,followers_count,fan_count")
    out["page"] = {"followers": page.get("followers_count"), "likes": page.get("fan_count"),
                   "daily": {m: metric(pid, m, "day") for m in PAGE_METRICS}}

    rows = {}
    try:
        for r in csv.DictReader(open(os.path.join(Q, "schedule.csv"), encoding="utf-8")):
            rows[f"{r['episode'].strip()}:{r['platform'].strip()}"] = r
    except FileNotFoundError:
        pass
    posted = json.load(open(os.path.join(Q, "posted.json"), encoding="utf-8"))
    posts = {}
    for key, rec in posted.items():
        oid = rec.get("post_id") or rec.get("video_id") or rec.get("id")
        if not oid:
            continue
        row = rows.get(key, {})
        reel = key.endswith(":facebook-reel")
        p = {"title": row.get("title", ""), "due_at": row.get("due_at", ""), "type": "reel" if reel else "album/image", "id": oid}
        try:
            f = "created_time,permalink_url,is_published,shares,comments.summary(true).limit(0),reactions.summary(true).limit(0)"
            if reel:
                f = "created_time,permalink_url,length,post_id,comments.summary(true).limit(0),likes.summary(true).limit(0)"
            o = call("GET", oid, fields=f)
            p.update({"created": o.get("created_time"), "link": o.get("permalink_url"), "published": o.get("is_published"),
                      "shares": (o.get("shares") or {}).get("count", 0),
                      "comments": ((o.get("comments") or {}).get("summary") or {}).get("total_count"),
                      "reactions": ((o.get("reactions") or o.get("likes") or {}).get("summary") or {}).get("total_count"),
                      "length_s": o.get("length"), "feed_post_id": o.get("post_id")})
        except FBError as e:
            p["error"] = str(e)[:150]
        if reel:
            p["metrics"] = reel_metrics(oid, p.get("feed_post_id"))
        else:
            p["metrics"] = {m: metric(oid, m) for m in POST_METRICS}
        posts[key] = p
    out["posts"] = posts
    with open(os.path.join(Q, "insights.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"saved insights for {len(posts)} posts")


if __name__ == "__main__":
    main()
