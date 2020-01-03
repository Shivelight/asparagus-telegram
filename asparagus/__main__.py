import json
import logging
import logging.handlers
import os
import re
import signal
import sys
import time

import feedparser
import requests

from .constant import TELEGRAM_API, FEED_NEWS, FEED_PKG_UPDATE_ALL
from .template import NEWS_TMPL, PKG_UPDATE_TMPL


# Logging utility
try:
    os.mkdir("logs")
except FileExistsError:
    pass


log_formatter = logging.Formatter(
    "[%(asctime)s][%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("asparagus")
log.setLevel(logging.DEBUG)
__streamlog = logging.StreamHandler()
__streamlog.setFormatter(log_formatter)
__streamlog.setLevel(logging.INFO)  # Stream should ignore DEBUG
__filelog = logging.handlers.TimedRotatingFileHandler(
    f"logs/asparagus.log", when="d", backupCount=5
)
__filelog.setFormatter(log_formatter)
log.addHandler(__filelog)
log.addHandler(__streamlog)


PID_FILE = "asparagus.pid"
CONFIG = {
    "API_TOKEN": "YOUR_BOT_API_TOKEN",
    "CHAT_ID": "YOUR_CHANNEL_ID",
    "LAST_NEWS": 0,
    "LAST_NEWS_ETAG": "",
    "LAST_PKG_UPDATE_ALL": 0,
    "LAST_PKG_UPDATE_ETAG": 0,
    "INTERVAL": 60 * 5,
}


# Currently the safest way to make Telegram compatible HTML.
# It clean up all HTML tag except hyperlink and code tag.
HTML_RE = re.compile(r"<(?!a href|/a|code|/code).*?>")


def clean_up_html(html):
    return HTML_RE.sub("", html)


def fetch_news():
    feed = feedparser.parse(FEED_NEWS, etag=CONFIG["LAST_NEWS_ETAG"])
    CONFIG["LAST_NEWS_ETAG"] = feed.etag
    if feed.status == 304:
        log.debug("fetch_news: no update")
        return

    for entry in reversed(feed.entries):
        published = time.mktime(entry.published_parsed)
        if published >= CONFIG["LAST_NEWS"]:
            text = NEWS_TMPL.format(
                date=entry.published,
                link=entry.link,
                title=entry.title,
                description=clean_up_html(entry.description),
                name=CONFIG["BOT_NAME"],
                username=CONFIG["BOT_USERNAME"],
            )
            msg = {
                "chat_id": CONFIG["CHAT_ID"],
                "text": text,
                "parse_mode": "HTML",
            }
            result = post("sendMessage", params=msg)["result"]
            log.debug(f"{result}")
            CONFIG["LAST_NEWS"] = published
            log.info(f'News: "{entry.title}" pushed')
            pin = {"chat_id": CONFIG["CHAT_ID"], "message_id": result["message_id"]}
            post("pinChatMessage", params=pin)
            log.info(f'News: "{entry.title}" pinned')

    CONFIG["LAST_NEWS"] += 0.1


def fetch_pkg_update():
    feed = feedparser.parse(FEED_PKG_UPDATE_ALL, etag=CONFIG["LAST_PKG_UPDATE_ETAG"])
    CONFIG["LAST_PKG_UPDATE_ETAG"] = feed.etag
    if feed.status == 304:
        log.debug("fetch_pkg_update: no update")
        return

    for entry in reversed(feed.entries):
        published = time.mktime(entry.published_parsed)
        if published >= CONFIG["LAST_PKG_UPDATE_ALL"]:
            category = ", ".join(tag["term"] for tag in entry.tags)
            text = PKG_UPDATE_TMPL.format(
                date=entry.published,
                category=category,
                link=entry.link,
                title=entry.title,
                description=entry.description,
                name=CONFIG["BOT_NAME"],
                username=CONFIG["BOT_USERNAME"],
            )
            msg = {
                "chat_id": CONFIG["CHAT_ID"],
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": True
            }
            post("sendMessage", params=msg)
            CONFIG["LAST_PKG_UPDATE_ALL"] = published
            log.info(f'Package: "{entry.title}" pushed')

    CONFIG["LAST_PKG_UPDATE_ALL"] += 0.1


def post(method, params=None):
    url = TELEGRAM_API.format(token=CONFIG["API_TOKEN"], method=method)
    res = requests.post(url, json=params)
    res.raise_for_status()
    return res.json()


def load_config():
    try:
        with open("config.json") as file:
            conf = json.load(file)
            CONFIG.update(conf)
    except (FileNotFoundError, KeyError):
        log.info(f"Creating {os.getcwd()}/config.json")
        log.info('Please setup your "config.json" file before restarting.')
        terminate()


def save_config():
    with open("config.json", "w+") as file:
        json.dump(CONFIG, file, indent=4)


def terminate(signo=None, _frame=None):
    log.info("Saving config.json")
    save_config()
    os.remove(PID_FILE)
    sys.exit()


def run():
    pid = str(os.getpid())
    if os.path.isfile(PID_FILE):
        log.error(f"{PID_FILE} already exists. Exiting..")
    with open(PID_FILE, "w") as file:
        file.write(pid)

    load_config()
    signal.signal(signal.SIGINT, terminate)

    me = post("getMe")["result"]
    CONFIG["BOT_ID"] = me["id"]
    CONFIG["BOT_USERNAME"] = me["username"]
    CONFIG["BOT_NAME"] = me["first_name"]

    log.info(f"BOT Name: {CONFIG['BOT_NAME']}")
    log.info(f"BOT Username: {CONFIG['BOT_USERNAME']}")
    log.info(f"Target Channel: {CONFIG['CHAT_ID']}")
    log.info(f"Fetch Interval: {CONFIG['INTERVAL']}s")

    while True:
        try:
            fetch_news()
            fetch_pkg_update()
            save_config()
            time.sleep(CONFIG["INTERVAL"])
        except Exception as e:
            log.exception(e)


if __name__ == "__main__":
    run()
