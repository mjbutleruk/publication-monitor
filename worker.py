"""Run from cron or a cloud scheduler (e.g. every hour)."""
from monitor import connect, setting, feeds_for_topic, scan, send_digest


def main():
    conn = connect()
    topics = [row[0] for row in conn.execute('SELECT name FROM topics')]
    feeds = [row[0] for row in conn.execute('SELECT url FROM sources')]
    total = 0
    for topic in topics:
        count, errors = scan(conn, topic, feeds_for_topic(topic, feeds))
        total += count
        print(f'{topic}: {count} new publications')
        for error in errors:
            print('WARNING:', error)
    print(f'Total new: {total}')
    try:
        print(send_digest(conn, setting(conn, 'frequency', 'daily')))
    except Exception as exc:
        print('Email delivery failed:', exc)
        raise


if __name__ == '__main__':
    main()
