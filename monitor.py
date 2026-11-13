"""Shared publication discovery, persistent notifications, and email delivery."""
import datetime as dt
import hashlib
import os
import re
import sqlite3
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote, urlsplit, urlunsplit

import feedparser
import requests
from bs4 import BeautifulSoup

DB = os.getenv('MONITOR_DB', os.path.join(os.path.dirname(__file__), 'monitor.db'))


def connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS topics (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    conn.execute('CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, url TEXT UNIQUE)')
    conn.execute('CREATE TABLE IF NOT EXISTS articles (id TEXT PRIMARY KEY, topic TEXT, title TEXT, url TEXT, source TEXT, published TEXT, summary TEXT, discovered TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, article_id TEXT NOT NULL, topic TEXT NOT NULL, created TEXT NOT NULL, read_at TEXT, emailed_at TEXT, UNIQUE(article_id,topic))')
    conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    conn.commit()
    return conn


def setting(conn, key, default=''):
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key, value):
    conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
    conn.commit()


def feeds_for_topic(topic, custom_feeds, news=True, arxiv=True, custom=True):
    targets = []
    if news:
        targets.append(('News / web', 'https://news.google.com/rss/search?q=' + quote(topic) + '&hl=en-US&gl=US&ceid=US:en'))
    if arxiv:
        targets.append(('arXiv', 'https://export.arxiv.org/api/query?search_query=all:' + quote(topic) + '&start=0&max_results=30&sortBy=submittedDate&sortOrder=descending'))
    if custom:
        targets.extend(('Blog / RSS', f) for f in custom_feeds)
    return targets


def scan(conn, topic, targets):
    """Returns (new count, error messages). No email is sent from here."""
    added, errors = 0, []
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for source, feed_url in targets:
        try:
            response = requests.get(feed_url, timeout=20, headers={'User-Agent': 'PublicationMonitor/1.1 (+RSS reader)'})
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(str(parsed.bozo_exception))
            for item in parsed.entries[:60]:
                title = BeautifulSoup(item.get('title', ''), 'html.parser').get_text(' ', strip=True)
                summary = BeautifulSoup(item.get('summary', ''), 'html.parser').get_text(' ', strip=True)
                summary = re.sub(r'\s+', ' ', summary)[:1200]
                link = item.get('link', '')
                if not title or not link.startswith(('https://', 'http://')):
                    continue
                if source == 'Blog / RSS' and not any(w.lower() in (title + ' ' + summary).lower() for w in re.findall(r'\w+', topic) if len(w) > 3):
                    continue
                parts = urlsplit(link)
                canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), '', ''))
                # Topic is part of the identity: the same link may be relevant to multiple topics.
                key = hashlib.sha256((topic + '\0' + canonical).encode()).hexdigest()
                cur = conn.execute('INSERT OR IGNORE INTO articles VALUES(?,?,?,?,?,?,?,?)', (key, topic, title, link, source, item.get('published', item.get('updated', '')), summary, now))
                if cur.rowcount:
                    conn.execute('INSERT OR IGNORE INTO notifications(article_id,topic,created) VALUES(?,?,?)', (key, topic, now))
                    added += 1
            conn.commit()
        except Exception as exc:
            errors.append(f'{source} ({feed_url}): {exc}')
    return added, errors


def pending(conn):
    return conn.execute('''SELECT n.id,a.topic,a.title,a.url,a.source,a.published,a.summary
        FROM notifications n JOIN articles a ON a.id=n.article_id
        WHERE n.emailed_at IS NULL ORDER BY n.id''').fetchall()


def email_configured():
    return all(os.getenv(k) for k in ('SMTP_HOST', 'SMTP_FROM', 'ALERT_EMAIL'))


def send_digest(conn, frequency='daily', force=False):
    """Sends pending items and marks them emailed only after successful SMTP delivery."""
    if not email_configured():
        return 'Email not configured (set SMTP_HOST, SMTP_FROM, ALERT_EMAIL).'
    if not force and frequency != 'immediate':
        last = setting(conn, 'last_email_at')
        if last:
            elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)
            if elapsed < dt.timedelta(days=7 if frequency == 'weekly' else 1):
                return 'Digest not due yet.'
    items = pending(conn)
    if not items:
        return 'No new publications to email.'
    msg = EmailMessage()
    msg['Subject'] = f'Publication Monitor: {len(items)} new publication(s)'
    msg['From'] = os.environ['SMTP_FROM']
    msg['To'] = os.environ['ALERT_EMAIL']
    lines = [f'{len(items)} new publications', '']
    for _, topic, title, url, source, published, summary in items[:100]:
        lines.extend([f'[{topic}] {title}', f'{source} | {published or "Date unavailable"}', url, summary[:500] or 'No source excerpt available.', ''])
    if len(items) > 100:
        lines.append(f'...and {len(items)-100} more. Open the app for the full list.')
    lines.append('Summaries above are excerpts from sources, not AI-generated analyses.')
    msg.set_content('\n'.join(lines))
    host = os.environ['SMTP_HOST']
    port = int(os.getenv('SMTP_PORT', '587'))
    user, password = os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD')
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if port != 465:
            server.starttls(context=ssl.create_default_context())
        if user:
            server.login(user, password or '')
        server.send_message(msg)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.executemany('UPDATE notifications SET emailed_at=? WHERE id=?', [(now, row[0]) for row in items])
    set_setting(conn, 'last_email_at', now)
    conn.commit()
    return f'Emailed {len(items)} publications.'
