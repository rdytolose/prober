# Updating an existing deployment

This release adds the new dashboard, drag-and-drop job submission, live per-link
progress, job cancellation, and in-UI prober token creation. No breaking
changes — existing data (jobs, outcomes, registered probers, `.env`, env-var
tokens) is preserved.

## What changes on disk

| File / table | Action |
| --- | --- |
| `coordinator/templates/*.html`, `coordinator/app.py`, `coordinator/db.py` | rewritten |
| `prober/worker.py`, `prober/reporter.py`, `prober/config.py` | updated |
| `scripts/watch_job.py`, `scripts/split_and_submit.py` | new |
| `pyproject.toml` | adds `python-multipart` dependency |
| SQLite table `prober_tokens` | created on first start (empty until you click "Generate token") |
| SQLite column `jobs.n_links` | added by lightweight auto-migration on first start |

You do **not** need to back up the database before updating — the change is
additive — but you can if you want extra safety (see end of this file).

---

## Stop the current job first (recommended)

If you currently have a long-running job (e.g. the 53 578-link one), stop the
prober before updating so it doesn't keep working in the background while you
swap binaries:

```bash
ssh vpn@<PROBER_IP>
cd ~/code/vpn-prober/deploy/prober
docker compose down
```

The job will stay in `claimed` status in the coordinator DB. After the update
you can either:
- cancel it from the dashboard (Stop button on the job page), or
- delete it from the API: `curl -X DELETE -H "Authorization: Bearer $ADMIN" https://<DOMAIN>/api/v1/jobs/<JOB_ID>`.

---

## Step 1 — push the new code to both VPS

On your **local machine** (where the new tarball is):

```bash
scp vpn-prober.tar.gz vpn@<COORDINATOR_IP>:~/
scp vpn-prober.tar.gz vpn@<PROBER_IP>:~/
```

---

## Step 2 — update the coordinator

```bash
ssh vpn@<COORDINATOR_IP>
cd ~/code/vpn-prober
# Replace files in-place; keeps deploy/coordinator/.env intact
tar -xzf ~/vpn-prober.tar.gz --strip-components=1

cd deploy/coordinator
docker compose up -d --build
```

This rebuilds the coordinator image with the new code, restarts the container,
and runs the schema migration on first start. The SQLite volume is preserved.

Check it came up:

```bash
docker compose logs --tail=30 coordinator
curl https://<DOMAIN>/health
```

Then open the dashboard in your browser:

```
https://<DOMAIN>/dashboard
```

(You'll see a login page — paste `COORDINATOR_ADMIN_TOKEN` from your `.env`.
It now stores a cookie, so you won't need `?token=` in the URL afterwards.)

---

## Step 3 — update the prober

```bash
ssh vpn@<PROBER_IP>
cd ~/code/vpn-prober
tar -xzf ~/vpn-prober.tar.gz --strip-components=1

cd deploy/prober
docker compose up -d --build
docker compose logs --tail=30 prober
```

You should see something like:

```
INFO prober.worker registered with coordinator at https://<DOMAIN>
INFO prober.worker [1/250] vless · ok · 412ms · de.cdn.com:443
INFO prober.worker [2/250] trojan · ok · 580ms · jp.cdn.com:443
...
INFO prober.worker flushed 10 outcome(s) for job <id>
```

Per-link logs and incremental flushing are now on by default.

---

## Step 4 — try the new features

1. **Dashboard:** progress bars, KPI counters, auto-refresh every 5 s.
2. **Jobs page (`/dashboard/jobs`):** full history with per-job progress.
3. **Job detail (`/dashboard/jobs/<id>`):** auto-refresh every 3 s while
   running, **Stop** button, live OK / FAIL counters.
4. **New job (`/dashboard/new`):** drag-and-drop a `.txt`, paste links into the
   textarea, or both. Lines starting with `#` are ignored.
5. **Nodes (`/dashboard/nodes`):** click **Generate token**, copy the one-shot
   install command, run it on a fresh prober VPS — no more manual `.env`
   editing.

---

## Step 5 — handle the leftover 53 K-link job

Two options:

**Option A — cancel and start fresh, smaller:**
```bash
# In the dashboard, open the giant job → click Stop.  Then:
python3 scripts/split_and_submit.py \
    --coordinator https://<DOMAIN> --token <ADMIN> \
    --links-file ~/links.txt --batch-size 500 \
    --urls https://www.google.com https://www.cloudflare.com \
    --label rerun
```
You'll get ~108 separate jobs of 500 links each. They run sequentially on
one prober (or in parallel across many), and each finishes in 5–40 minutes
instead of weeks. Per-job results appear on the dashboard as they complete.

**Option B — let it run:**
The prober is now cancel-aware. If you change your mind mid-way, hit Stop on
the job page and the prober halts within seconds (after the current link).

---

## Watching from the terminal (optional)

```bash
python3 scripts/watch_job.py \
    --coordinator https://<DOMAIN> --token <ADMIN> --job-id <JOB_ID>
```

Prints a live progress bar with ETA:

```
[████████████·············] 1234/5000   24.7%  ok=987  fail=247  3.21/s  eta=1172s  status=claimed
```

---

## Backups (optional)

Before any update you can snapshot the coordinator database in one line:

```bash
ssh vpn@<COORDINATOR_IP> \
    'docker run --rm -v vpn-prober_coordinator-data:/d -v $HOME:/b alpine \
     sh -c "cd /d && tar czf /b/coordinator-data-$(date +%F-%H%M).tar.gz ."'
```

Restoring is the same with `tar xzf`.

---

## Rollback (if something breaks)

```bash
# On either server
cd ~/code/vpn-prober/deploy/<role>
docker compose down
git checkout <previous-commit>     # or re-extract the old tarball
docker compose up -d --build
```

The database is forward-compatible: the new `n_links` column and
`prober_tokens` table are simply ignored by older code.

---

## TL;DR — 4 commands per server

**Coordinator:**
```bash
cd ~/code/vpn-prober && tar -xzf ~/vpn-prober.tar.gz --strip-components=1
cd deploy/coordinator && docker compose up -d --build
```

**Prober:**
```bash
cd ~/code/vpn-prober && tar -xzf ~/vpn-prober.tar.gz --strip-components=1
cd deploy/prober && docker compose up -d --build
```

That's the whole update.
