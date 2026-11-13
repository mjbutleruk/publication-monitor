# Publication Monitor — email + in-app notifications

Local Streamlit app monitoring Google News RSS, arXiv, and custom RSS/Atom feeds. New results are stored in SQLite and shown in a notification inbox. SMTP can deliver immediate, daily, or weekly digests.

## Start the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Add topics and optional blog RSS feeds. Click **Check for new publications**. The **Notifications** tab displays new findings, with unread/read state.

## Configure email

Copy the variable names from `.env.example` into your shell or deployment platform's **secrets/environment variables**. Do not commit passwords to version control. Set `SMTP_HOST`, `SMTP_FROM`, and `ALERT_EMAIL`; normally also `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_PORT` (587 for STARTTLS or 465 for implicit TLS). Use your email provider's app password or SMTP credentials. Example for Linux/macOS:

```bash
export SMTP_HOST='smtp.example.com'
export SMTP_PORT='587'
export SMTP_USER='smtp-user'
export SMTP_PASSWORD='app-password'
export SMTP_FROM='alerts@example.com'
export ALERT_EMAIL='you@example.com'
```

The app sidebar allows you to choose **immediate**, **daily**, or **weekly**, and to send pending email manually. Only newly discovered publications are queued for email; a successfully sent email marks them as delivered.

## Automate checks

Schedule the following command in cron, a hosted scheduled job, or a background worker, using the same `MONITOR_DB` database path and environment variables as the Streamlit app:

```bash
python worker.py
```

Example cron entry for hourly checks (run `crontab -e`):

```
0 * * * * cd /path/to/publication-monitor && /path/to/python worker.py >> monitor.log 2>&1
```

The worker checks all saved topics, writes in-app notifications, and sends pending emails according to the digest frequency. A scheduled worker and persistent shared storage are required for monitoring while the app is closed. On ephemeral cloud hosting, use a persistent database service or volume; SQLite on temporary disk will lose data. For multiple workers, add a distributed lock to prevent overlapping checks and duplicate sends.

## Limitations

- Discovery is **not universal**: private content, paywalls, blogs without feeds, and publishers without accessible indexes may be missed.
- The app displays source excerpts, **not AI-generated summaries**. A future AI integration could generate summaries and identify meaningful changes.
- Google News RSS and arXiv are discovery sources, not comprehensive indexes of all publications.
- The app sends email digests, **not device push notifications**. In-app notifications appear in the inbox when you open the app.
- Topic matching in custom RSS feeds is simple keyword matching; link-based deduplication does not merge articles covering the same event.
- SMTP credentials are provided only through environment variables, not entered in the app.
- The starter has no login or multi-user isolation; deploy privately or add authentication before exposing it publicly.
- Respect source terms, licensing, rate limits, and robots restrictions.
