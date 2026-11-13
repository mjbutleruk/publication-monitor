import streamlit as st

import os

for key in (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "ALERT_EMAIL",
):
    if key in st.secrets:
        os.environ[key] = str(st.secrets[key])

from monitor import connect, setting, set_setting, feeds_for_topic, scan, send_digest, email_configured

st.set_page_config(page_title='Publication Monitor', page_icon='📡', layout='wide')
conn = connect()
st.title('📡 Publication Monitor')
st.caption('Discover research, news, web publications, and RSS/Atom blogs. Review alerts in-app and receive email digests.')

with st.sidebar:
    st.header('Topics')
    with st.form('topic'):
        topic = st.text_input('Add a topic', placeholder='e.g. solid-state batteries')
        if st.form_submit_button('Add topic') and topic.strip():
            conn.execute('INSERT OR IGNORE INTO topics(name) VALUES(?)', (topic.strip(),))
            conn.commit()
    topics = [r[0] for r in conn.execute('SELECT name FROM topics ORDER BY name')]
    selected = st.selectbox('Monitor topic', topics) if topics else None
    st.header('Blog and website feeds')
    with st.form('feed'):
        url = st.text_input('RSS / Atom URL', placeholder='https://example.com/feed')
        if st.form_submit_button('Add feed'):
            if url.startswith(('https://', 'http://')):
                conn.execute('INSERT OR IGNORE INTO sources(url) VALUES(?)', (url,))
                conn.commit()
            else:
                st.warning('Enter a valid http(s) feed URL.')
    feeds = [r[0] for r in conn.execute('SELECT url FROM sources')]
    for feed in feeds:
        st.caption(feed)
    st.header('Email alerts')
    options = ['immediate', 'daily', 'weekly']
    current = setting(conn, 'frequency', 'daily')
    frequency = st.selectbox('Digest frequency', options, index=options.index(current) if current in options else 1)
    if frequency != current:
        set_setting(conn, 'frequency', frequency)
    st.caption('Immediate means after the next scheduled or manual check, not real-time push.')
    st.caption('SMTP configured' if email_configured() else 'Email not configured — see README.')
    if st.button('Send pending email now'):
        try:
            st.info(send_digest(conn, frequency, force=True))
        except Exception as exc:
            st.error(f'Email delivery failed: {exc}')

inbox, publications = st.tabs(['🔔 Notifications', '📚 Publications'])
with inbox:
    unread = conn.execute('SELECT COUNT(*) FROM notifications WHERE read_at IS NULL').fetchone()[0]
    st.subheader(f'Notification inbox · {unread} unread')
    if st.button('Mark all as read'):
        conn.execute("UPDATE notifications SET read_at=datetime('now') WHERE read_at IS NULL")
        conn.commit()
        st.rerun()
    notices = conn.execute('''SELECT n.id,a.topic,a.title,a.url,a.source,n.created,n.read_at
        FROM notifications n JOIN articles a ON a.id=n.article_id ORDER BY n.id DESC LIMIT 200''').fetchall()
    if not notices:
        st.info('No notifications yet. Run a publication check to discover new items.')
    for nid, topic, title, url, source, created, read_at in notices:
        with st.container(border=True):
            st.markdown(f'**[{title}]({url})**')
            st.caption(f'{"Read" if read_at else "Unread"} · {topic} · {source} · {created[:16]} UTC')
            if not read_at and st.button('Mark read', key=f'read-{nid}'):
                conn.execute("UPDATE notifications SET read_at=datetime('now') WHERE id=?", (nid,))
                conn.commit()
                st.rerun()

with publications:
    if not selected:
        st.info('Add a topic in the sidebar to begin.')
    else:
        use_news = st.checkbox('News and web publications (Google News RSS)', True)
        use_arxiv = st.checkbox('Research preprints (arXiv)', True)
        use_custom = st.checkbox('Custom blogs and RSS feeds', True)
        if st.button('🔄 Check for new publications', type='primary'):
            with st.spinner('Checking feeds…'):
                count, errors = scan(conn, selected, feeds_for_topic(selected, feeds, use_news, use_arxiv, use_custom))
            st.success(f'Found {count} new publication(s). Notifications saved in the inbox.')
            for err in errors:
                st.warning(err)
            if setting(conn, 'frequency', 'daily') == 'immediate' and count:
                try:
                    st.info(send_digest(conn, 'immediate'))
                except Exception as exc:
                    st.warning(f'Email delivery failed: {exc}')
        rows = conn.execute('SELECT title,url,source,published,summary,discovered FROM articles WHERE topic=? ORDER BY discovered DESC', (selected,)).fetchall()
        st.subheader(f'{selected} · {len(rows)} saved publications')
        query = st.text_input('Filter results')
        for title, url, source, published, summary, discovered in rows:
            if query.lower() not in (title + ' ' + summary).lower():
                continue
            with st.container(border=True):
                st.markdown(f'**[{title}]({url})**')
                st.caption(f'{source} · {published or "Publication date unavailable"} · Discovered {discovered[:10]}')
                st.write(summary or 'No abstract provided by the source.')
                st.caption('Source excerpt only; AI-generated summaries are not enabled yet.')
