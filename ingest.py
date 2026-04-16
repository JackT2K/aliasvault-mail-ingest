#!/usr/bin/env python3
import os
import time
import ssl
import sqlite3
import socket
import traceback
import imaplib
import smtplib
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import msal


def getenv(name, default=None, required=False):
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise SystemExit(f"Missing required env var: {name}")
    return v


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


TENANT_ID     = getenv("TENANT_ID", required=True)
CLIENT_ID     = getenv("CLIENT_ID", required=True)
CLIENT_SECRET = getenv("CLIENT_SECRET", required=True)

MAILBOX       = getenv("MAILBOX", required=True).strip().lower()

SMTP_HOST     = getenv("SMTP_HOST", required=True)
SMTP_PORT     = int(getenv("SMTP_PORT", "25"))

IMAP_HOST     = getenv("IMAP_HOST", "outlook.office365.com")
IMAP_PORT     = int(getenv("IMAP_PORT", "993"))
OAUTH_SCOPE   = "https://outlook.office365.com/.default"

POLL_SECONDS    = int(getenv("POLL_SECONDS", "60"))
MAX_PER_CYCLE   = int(getenv("MAX_PER_CYCLE", "5"))
BACKOFF_SECONDS = int(getenv("BACKOFF_SECONDS", "90"))

FILTER_DOMAIN   = getenv("FILTER_RCPT_DOMAIN", "domain.tld").strip().lower()
KEEP_UNSEEN     = getenv("KEEP_UNSEEN", "true").lower() in ("1","true","yes")
MARK_AS_READ    = getenv("MARK_AS_READ", "false").lower() in ("1","true","yes")
DRY_RUN         = getenv("DRY_RUN", "false").lower() in ("1","true","yes")

DB_PATH       = getenv("DB_PATH", "state.db")


def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS seen (
        msgid TEXT PRIMARY KEY,
        imap_uid TEXT,
        ts INTEGER
      )
    """)
    con.commit()
    return con


def already_seen(con, msgid):
    cur = con.cursor()
    cur.execute("SELECT 1 FROM seen WHERE msgid=?", (msgid,))
    return cur.fetchone() is not None


def mark_seen(con, msgid, uid):
    cur = con.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO seen (msgid, imap_uid, ts) VALUES (?, ?, strftime('%s','now'))",
        (msgid, uid)
    )
    con.commit()


def parse_message(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


def extract_recipients(msg):
    headers = []
    for h in ("Delivered-To", "X-Original-To", "To", "Cc"):
        headers.extend(msg.get_all(h, []))

    rcpts = []
    for _, addr in getaddresses(headers):
        addr = (addr or "").strip().lower()
        if addr.endswith("@" + FILTER_DOMAIN):
            rcpts.append(addr)

    seen = set()
    out = []
    for r in rcpts:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def get_access_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=[OAUTH_SCOPE])
    if "access_token" not in result:
        raise RuntimeError(result)
    return result["access_token"]


def xoauth2_bytes(user, token):
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode("utf-8")


def connect_imap():
    token = get_access_token()
    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
    imap.authenticate("XOAUTH2", lambda _: xoauth2_bytes(MAILBOX, token))
    imap.select("INBOX")
    return imap


def smtp_inject(raw, env_from, rcpt_to):
    if DRY_RUN:
        log(f"[DRY_RUN] From={env_from} To={rcpt_to}")
        return
    s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    try:
        s.sendmail(env_from, rcpt_to, raw)
    finally:
        s.quit()


def process_batch(con, imap):
    _, data = imap.search(None, "UNSEEN")
    uids = data[0].split()

    if not uids:
        log("No new messages (UNSEEN).")
        return

    log(f"Found {len(uids)} unseen message(s). Processing up to {MAX_PER_CYCLE}.")

    for uid in uids[:MAX_PER_CYCLE]:
        uid_s = uid.decode(errors="ignore")
        _, msgdata = imap.fetch(uid, "(RFC822)")
        raw = msgdata[0][1]
        msg = parse_message(raw)
        msgid = msg.get("Message-ID") or f"UID-{uid_s}"

        if already_seen(con, msgid):
            continue

        rcpt_to = extract_recipients(msg)
        if not rcpt_to:
            mark_seen(con, msgid, uid_s)
            log(f"Skipped {msgid} - no @{FILTER_DOMAIN} recipient")
            continue

        env_from = msg.get("From") or "ingest@localhost"
        if "<" in env_from and ">" in env_from:
            env_from = env_from.split("<", 1)[1].split(">", 1)[0]

        smtp_inject(raw, env_from, rcpt_to)
        mark_seen(con, msgid, uid_s)

        if MARK_AS_READ and not KEEP_UNSEEN:
            imap.store(uid, "+FLAGS", "\\Seen")

        log(f"Forwarded {msgid} -> {rcpt_to}")


def main():
    log("Starting AliasVault Mail Ingest")
    con = db_init()
    imap = None

    while True:
        try:
            if imap is None:
                imap = connect_imap()

            process_batch(con, imap)
            time.sleep(POLL_SECONDS)

        except imaplib.IMAP4.abort as e:
            log(f"IMAP throttled: {e}")
            try:
                imap.logout()
            except Exception:
                pass
            imap = None
            time.sleep(BACKOFF_SECONDS)

        except Exception as e:
            log(f"Error: {e}")
            traceback.print_exc()
            try:
                imap.logout()
            except Exception:
                pass
            imap = None
            time.sleep(BACKOFF_SECONDS)


if __name__ == "__main__":
    main()