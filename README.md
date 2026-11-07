# vagantiya-publish

Publisher **code only** for the වගන්තිය Facebook Page (and the R2 upload helper used by English from Zero).

This repo is public so GitHub Actions is free. It holds **no data**: the schedule, captions, posts, videos, links and logs live in a private repository. Each workflow checks that data out with a repository secret, runs the code in `publish/` and `tools/` against it, saves the results back to the private repository, and prints only an `ok`/`failed` line here.

| Workflow | When | What it does |
|---|---|---|
| `publish.yml` | 5 times a day + manual | Creates the scheduled Facebook posts and first comments |
| `insights.yml` | daily | Reads Page / post stats |
| `check.yml` | manual | Checks the Facebook token and R2 secrets (posts nothing) |
| `reel_test.yml` | manual | Uploads a draft Reel, checks it, deletes it |
| `r2.yml` | every 10 min + manual | Copies media from `upload/*` branches of the private repo to Cloudflare R2 |
| `clip.yml`, `probe.yml` | manual | Cuts a clause picture / probes an official page for a post |
| `keepalive.yml` | monthly | One empty commit so GitHub does not switch the schedules off |

Secrets needed: `FB_PAGE_ID`, `FB_PAGE_TOKEN`, `R2_*`, and `HUB_TOKEN` (fine-grained token, private data repo only, Contents read/write).
