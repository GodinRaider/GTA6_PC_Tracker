#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GTA VI PC Race -> Telegram.

Проверяет страницу-трекер https://vuyp.github.io/gta6-pc-race/ и присылает в
Telegram новые записи из раздела Updates. Состояние (какие записи уже
отправлены) хранится в state.json прямо в репозитории — GitHub Actions
коммитит его обратно после каждого прогона.

Только стандартная библиотека Python, ничего устанавливать не нужно.

Переменные окружения:
  TELEGRAM_TOKEN    — токен бота от @BotFather (секрет GitHub)
  TELEGRAM_CHAT_ID  — ваш chat_id (секрет GitHub)
  STATE_FILE        — путь к state.json (по умолчанию ./state.json)
  DRY_RUN=1         — не отправлять в Telegram, только напечатать в консоль
"""

import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

PAGE_URL = "https://vuyp.github.io/gta6-pc-race/"
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# Строка вида "12:28 24 Nov" на отдельной строке — метка записи в разделе Updates.
TIMESTAMP_RE = re.compile(
    r"^(\d{2}:\d{2}) (\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))$",
    re.M,
)

# Ключевые слова, по которым запись помечается как важная.
IMPORTANT_WORDS = (
    "stage 6", "stage 7", "playable", "in-game", "ingame",
    "takedown", "take-down", "take down", "discord", "banned",
    "rockstar", "take-two", "dmca", "cease", "notice", "legal",
)

MAX_TG_LEN = 4000


def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "gta6-pc-race-tracker/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def to_text(raw_html: str) -> str:
    """Вычищает HTML до читаемого текста с сохранением разбивки по строкам."""
    raw_html = re.sub(r"<script\b.*?</script>", " ", raw_html, flags=re.S | re.I)
    raw_html = re.sub(r"<style\b.*?</style>", " ", raw_html, flags=re.S | re.I)
    raw_html = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.I)
    raw_html = re.sub(
        r"</(?:p|div|li|h[1-6]|section|article)>", "\n", raw_html, flags=re.I
    )
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_updates(text: str):
    """Возвращает список (timestamp, title, body) в порядке появления на странице."""
    matches = list(TIMESTAMP_RE.finditer(text))
    updates = []
    for i, m in enumerate(matches):
        ts = "%s %s" % (m.group(1), m.group(2))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip("\n")
        chunk = re.sub(r"See \d+ earlier updates", "", chunk)
        lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
        if not lines:
            continue
        updates.append((ts, lines[0], " ".join(lines[1:])))
    return updates


def send_telegram(message: str) -> None:
    api = "https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN
    # Telegram не принимает сообщения длиннее 4096 символов — режем.
    parts = [message[i:i + MAX_TG_LEN] for i in range(0, len(message), MAX_TG_LEN)]
    for part in parts:
        data = urllib.parse.urlencode(
            {"chat_id": TELEGRAM_CHAT_ID, "text": part, "disable_web_page_preview": "true"}
        ).encode()
        urllib.request.urlopen(urllib.request.Request(api, data=data), timeout=30).read()


def main() -> int:
    raw = http_get(PAGE_URL)
    updates = parse_updates(to_text(raw))
    if not updates:
        print("ОШИБКА: на странице не найдено ни одной записи Updates — "
              "возможно, разметка изменилась и парсер нужно поправить.")
        return 1

    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    if not state:
        # Первый запуск: запоминаем всё, что уже есть, ничего не отправляем,
        # чтобы не завалить чат полудесятком старых новостей.
        for ts, title, _ in updates:
            state[ts] = title
        print("Первый запуск: запомнил %d существующих записей, ничего не отправил." % len(state))
        if not DRY_RUN:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
        return 0

    new = [(ts, title, body) for ts, title, body in updates if ts not in state]
    print("Записей на странице: %d, новых: %d" % (len(updates), len(new)))

    sent = 0
    for ts, title, body in new:
        body = re.sub(r"\s+", " ", body).strip()
        if len(body) > 1500:
            body = body[:1497] + "…"
        is_important = any(
            w in (title + " " + body).lower() for w in IMPORTANT_WORDS
        )
        tag = "⚠️ Важное" if is_important else "ℹ️ Обновление"
        message = "🚗 GTA VI PC Race (%s UTC)\n%s\n%s\n\n%s" % (
            ts, tag, title, body,
        )
        if DRY_RUN:
            print("---\n" + message)
        else:
            send_telegram(message)
        state[ts] = title
        sent += 1

    if not DRY_RUN and sent:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # прокидываем наверх, чтобы Actions пометил прогон красным
        print("Сбой проверки: %r" % exc)
        if not DRY_RUN and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            try:
                send_telegram("🚗 GTA VI PC Race: не удалось проверить страницу (%r). "
                              "Скорее всего, сайт лежит — загляните сами: %s"
                              % (exc, PAGE_URL))
            except Exception:
                pass
        sys.exit(1)
