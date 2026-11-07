"""Safe Reel API test: uploads queue/reel_test_request.txt's r2:<folder>/<file>.mp4 as a DRAFT Reel (never public),
waits for Facebook to process it, records the result in queue/reel_test.json, then deletes the draft."""
import json, time, datetime as dt
from fb import reel_post, call, FBError

ref = open("../queue/reel_test_request.txt").read().split()[0]
url = json.load(open("../queue/r2.json"))[ref]["url"]
out = {"tested_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "file": ref}
vid = None
try:
    vid = reel_post(url, "test (draft, deleted automatically)", draft=True)
    out["draft_created"] = True
    for _ in range(36):
        st = call("GET", vid, fields="status").get("status", {})
        out["status"] = st
        if st.get("video_status") in ("ready", "error") or st.get("processing_phase", {}).get("status") in ("complete", "error"):
            break
        time.sleep(10)
    out["ok"] = out["status"].get("video_status") != "error"
except FBError as e:
    out.update(ok=False, error=str(e)[:400])
finally:
    if vid:
        try:
            call("DELETE", vid); out["draft_deleted"] = True
        except FBError as e:
            out["draft_deleted"] = str(e)[:200]
json.dump(out, open("../queue/reel_test.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(out, indent=1))
