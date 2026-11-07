"""Safe setup check: posts NOTHING. Verifies the Facebook Page token and the R2 secrets, writes queue/check.json.

Run by the "Check setup" workflow (push queue/check_request.txt, or run it by hand in Actions)."""
import os, json, datetime as dt
from fb import call, creds, FBError

out = {"checked_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

# Facebook
try:
    pid, _ = creds()
    page = call("GET", pid, fields="name,username,followers_count,fan_count,category")
    out["facebook"] = {"ok": True, "page": page.get("name"), "username": page.get("username"),
                       "followers": page.get("followers_count"), "category": page.get("category")}
    try:
        call("GET", f"{pid}/feed", limit="1")
        out["facebook"]["can_read_feed"] = True
    except FBError as e:
        out["facebook"]["can_read_feed"] = str(e)[:200]
    try:
        call("GET", f"{pid}/insights", metric="page_follows", period="day")
        out["facebook"]["can_read_insights"] = True
    except FBError as e:
        out["facebook"]["can_read_insights"] = str(e)[:200]
except (FBError, SystemExit) as e:
    out["facebook"] = {"ok": False, "error": str(e)[:300]}

# What the Page shows: recent feed + published posts, and every recorded post's own state
try:
    pid, _ = creds()
    f = "id,created_time,status_type,is_published,is_hidden,permalink_url,message"
    out["feed"] = [{k: (v[:60] if k == "message" else v) for k, v in x.items()} for x in call("GET", f"{pid}/feed", fields=f, limit="10").get("data", [])]
    out["published_posts"] = [x.get("id") for x in call("GET", f"{pid}/published_posts", fields="id", limit="10").get("data", [])]
    posted = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "queue", "posted.json")))
    out["recorded"] = {}
    for k, v in posted.items():
        try:
            out["recorded"][k] = call("GET", v["post_id"], fields="is_published,permalink_url,created_time,status_type" if "_" in v["post_id"] else "id,created_time,link")
        except FBError as e:
            out["recorded"][k] = str(e)[:200]
except Exception as e:
    out["feed_error"] = str(e)[:300]

# R2
need = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_URL"]
missing = [k for k in need if not os.environ.get(k, "").strip()]
if missing:
    out["r2"] = {"ok": False, "missing": missing}
else:
    try:
        import boto3
        s3 = boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID'].strip()}.r2.cloudflarestorage.com",
                          aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
                          aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(), region_name="auto")
        bucket = os.environ["R2_BUCKET"].strip()
        key = "vagantiya/_check.txt"
        s3.put_object(Bucket=bucket, Key=key, Body=b"ok", ContentType="text/plain")
        s3.delete_object(Bucket=bucket, Key=key)
        out["r2"] = {"ok": True, "write_test": "passed", "public_url_set": True}
        # Whole-bucket usage (read-only): total + per project folder + per file type, to plan against the 10 GB free tier
        usage, total, count = {}, 0, 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for o in page.get("Contents", []):
                k, size = o["Key"], o["Size"]
                top = k.split("/", 1)[0] if "/" in k else "(root)"
                ext = k.rsplit(".", 1)[-1].lower() if "." in k.rsplit("/", 1)[-1] else "-"
                u = usage.setdefault(top, {"files": 0, "bytes": 0, "by_type": {}})
                u["files"] += 1; u["bytes"] += size
                t = u["by_type"].setdefault(ext, {"files": 0, "bytes": 0, "max": 0})
                t["files"] += 1; t["bytes"] += size; t["max"] = max(t["max"], size)
                total += size; count += 1
        out["r2_usage"] = {"total_bytes": total, "total_gb": round(total / 1e9, 3), "files": count, "by_folder": usage}
    except Exception as e:
        out["r2"] = {"ok": False, "error": str(e)[:300]}

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Links (queue/check_links.txt, one per line): would the publisher accept them?
lf = os.path.join(root, "queue", "check_links.txt")
if os.path.exists(lf):
    from publish import broken_links
    links = [l.strip() for l in open(lf) if l.strip().startswith("http")]
    bad = broken_links("\n".join(links))
    out["links"] = {u: ("NOT OPENING" if u in bad else "ok") for u in links}

json.dump(out, open(os.path.join(root, "queue", "check.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps(out, indent=1, ensure_ascii=False))
