
#!/usr/bin/env python3
"""SolveEase GapHunter: World Bank procurement opportunity discovery.

Source: World Bank Group Procurement Notice dataset.
Delivery: Telegram.
Scheduling and persistent state: GitHub Actions + state.json.

A future deadline does not establish applicant eligibility or guarantee
that a notice remains open. Always check the official notice.
"""

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "SolveEase GapHunter"
VERSION = "1.0.0"

API_BASE = (
    "https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice"
)
DATASET_ID = "DS00979"
RESOURCE_ID = "RS00909"
OFFICIAL_HOSTS = (
    "worldbank.org",
    "worldbankgroup.org",
)

STATE_PATH = Path(os.getenv("STATE_FILE", "state.json"))
TIMEOUT = 25
MAX_PAGES = max(1, min(int(os.getenv("MAX_PAGES", "5")), 25))
PAGE_SIZE = 1000
MAX_RESULTS = max(1, min(int(os.getenv("MAX_RESULTS", "8")), 15))
MAX_SEEN = 5000
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# Intentional narrow focus: service/consultancy opportunities, not every notice.
RELEVANCE_TERMS = {
    "consulting", "consultant", "consultancy", "non-consulting services",
    "training", "capacity building", "software", "information technology",
    "digital", "website", "web development", "data analysis", "data collection",
    "research", "translation", "interpretation", "graphic design",
    "communications", "communication", "evaluation", "monitoring",
    "audit", "accounting", "financial services", "cybersecurity",
    "cloud services", "database", "maintenance services", "cleaning services",
    "logistics services", "transport services", "printing services",
    "media services", "photography", "catering services",
    "security services", "event management", "project management",
    "engineering services", "architecture", "environmental services",
    "social services", "legal services", "human resources",
    "supply of computers", "supply of software", "it equipment",
}

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_date(value):
    """Parse common source date formats without guessing ambiguous dates."""
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        return datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        ).date()
    except ValueError:
        pass

    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:11], fmt).date()
        except ValueError:
            continue

    # Do not guess between DD/MM/YYYY and MM/DD/YYYY.
    return None


def official_url(value):
    """Only return source URLs hosted on World Bank domains."""
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""

    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return ""

    if not any(host == domain or host.endswith("." + domain)
               for domain in OFFICIAL_HOSTS):
        return ""

    return raw


def request_json(url, attempts=3):
    """Bounded retry for transient HTTP/network failures."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME}/{VERSION}",
            "Accept": "application/json",
        },
    )

    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"Unexpected HTTP status {response.status}"
                    )
                raw = response.read(8_000_000)
            return json.loads(raw.decode("utf-8"))

        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt == attempts - 1:
                raise RuntimeError(
                    f"Source returned HTTP {exc.code}"
                ) from exc
            retry_after = exc.headers.get("Retry-After", "")
            try:
                delay = min(max(int(retry_after), 1), 20)
            except ValueError:
                delay = 2 ** attempt
            time.sleep(delay)

        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(
                    f"Source request failed: {type(exc).__name__}"
                ) from exc
            time.sleep(2 ** attempt)

    raise RuntimeError("Source request failed after retries")


def fetch_notices():
    """Read bounded pages from the official dataset API."""
    today = datetime.now(timezone.utc).date()
    notices = {}
    pages_read = 0
    records_read = 0

    for page in range(MAX_PAGES):
        params = urllib.parse.urlencode({
            "datasetId": DATASET_ID,
            "resourceId": RESOURCE_ID,
            "top": PAGE_SIZE,
            "skip": page * PAGE_SIZE,
            "type": "json",
        })
        payload = request_json(f"{API_BASE}?{params}")

        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected API response: expected JSON object")

        records = payload.get("data")
        if not isinstance(records, list):
            raise RuntimeError(
                "Unexpected API schema: expected a 'data' list"
            )

        pages_read += 1
        records_read += len(records)

        if not records:
            break

        for row in records:
            if not isinstance(row, dict):
                continue

            notice_id = str(row.get("id") or "").strip()
            title = str(row.get("bid_description") or "").strip()
            link = official_url(row.get("url"))
            deadline_raw = row.get("deadline_date")
            deadline = parse_date(deadline_raw)

            # No invented links, no expired leads, no unknown deadlines.
            if not notice_id or not title or not link or deadline is None:
                continue
            if deadline < today:
                continue

            category = str(row.get("procurement_category") or "").strip()
            method = str(row.get("procurement_method") or "").strip()
            sector = str(row.get("sector") or "").strip()
            searchable = " ".join((title, category, method, sector)).lower()

            matched_terms = sorted(
                term for term in RELEVANCE_TERMS if term in searchable
            )

            # Prefer service/consultancy notices relevant to our audience.
            if not matched_terms:
                continue

            item_id = hashlib.sha256(
                f"world-bank:{notice_id}".encode("utf-8")
            ).hexdigest()

            notices[item_id] = {
                "id": item_id,
                "notice_id": notice_id,
                "title": title[:500],
                "url": link,
                "country": str(
                    row.get("country_name") or "Not specified"
                ).strip()[:120],
                "region": str(row.get("region") or "").strip()[:120],
                "deadline": deadline.isoformat(),
                "published": str(row.get("publication_date") or "").strip()[:40],
                "notice_type": str(row.get("notice_type") or "").strip()[:100],
                "category": category[:160],
                "method": method[:160],
                "sector": sector[:160],
                "matched_terms": matched_terms[:5],
            }

        if len(records) < PAGE_SIZE:
            break

    # Nearest deadlines first; stable ID breaks ties.
    ranked = sorted(
        notices.values(),
        key=lambda item: (item["deadline"], item["id"]),
    )

    return ranked, {
        "pages_read": pages_read,
        "records_read": records_read,
        "matching_open_deadline_notices": len(ranked),
        "source": API_BASE,
    }


def load_state():
    if not STATE_PATH.exists():
        return {"seen": [], "updated_at": None}

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("seen", []), list):
            raise ValueError("Unexpected state format")
        return {
            "seen": [str(x) for x in data.get("seen", [])][-MAX_SEEN:],
            "updated_at": data.get("updated_at"),
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot read {STATE_PATH}; refusing to overwrite it: {exc}"
        ) from exc


def save_state(seen_ids):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seen": list(dict.fromkeys(seen_ids))[-MAX_SEEN:],
        "updated_at": utc_now(),
    }
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(STATE_PATH)


def telegram_send(token, chat_id, text):
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        result = json.loads(response.read(1_000_000).decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError("Telegram did not accept the message")


def format_notice(item, number):
    title = html.escape(item["title"])
    link = html.escape(item["url"], quote=True)
    country = html.escape(item["country"])
    deadline = html.escape(item["deadline"])
    category = html.escape(item["category"] or "Not specified")
    method = html.escape(item["method"] or "Not specified")
    published = html.escape(item["published"] or "Not supplied")
    sector = html.escape(item["sector"] or "Not supplied")
    matched = html.escape(", ".join(item["matched_terms"]))

    return (
        f"<b>{number}. <a href=\"{link}\">{title}</a></b>\n"
        f"Country: {country}\n"
        f"Deadline: <b>{deadline}</b>\n"
        f"Category: {category}\n"
        f"Method: {method}\n"
        f"Sector: {sector}\n"
        f"Published: {published}\n"
        f"Matched because: {matched}\n"
        "Status: Source-listed; confirm the notice and your eligibility.\n"
    )


def build_messages(items, stats, errors):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = (
        f"<b>{APP_NAME} · {VERSION}</b>\n"
        f"World Bank procurement scan · {stamp}\n"
        f"Records checked: {stats['records_read']}\n"
        f"Relevant future-deadline matches: "
        f"{stats['matching_open_deadline_notices']}\n\n"
    )

    if not items:
        body = (
            "No new matching notices with parseable future deadlines "
            "were found in the pages checked."
        )
        messages = [header + body]
    else:
        messages = []
        current = header
        for index, item in enumerate(items, 1):
            block = format_notice(item, index)
            if len(current) + len(block) > 3600 and current != header:
                messages.append(current)
                current = header
            current += block + "\n"
        if current.strip():
            messages.append(current)

    if errors:
        warning = "\n<b>Warnings</b>\n" + html.escape("; ".join(errors)[:500])
        if len(messages[-1]) + len(warning) < 3900:
            messages[-1] += warning

    return messages


def write_github_summary(stats, sent_count, errors, dry_run):
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return

    status = "DRY RUN — no Telegram message sent" if dry_run else "Completed"
    lines = [
        f"# {APP_NAME} run report",
        "",
        f"- Status: {status}",
        f"- UTC time: {utc_now()}",
        f"- API pages read: {stats['pages_read']}",
        f"- Records read: {stats['records_read']}",
        f"- Relevant notices with future deadlines: "
        f"{stats['matching_open_deadline_notices']}",
        f"- New notices selected: {sent_count}",
        "- Eligibility: not independently verified",
        "- Deadline status: future date in dataset; check official notice",
        "",
    ]
    if errors:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {error}" for error in errors)

    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not DRY_RUN and (not token or not chat_id):
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in GitHub Secrets."
        )

    state = load_state()
    seen = set(state["seen"])
    errors = []

    notices, stats = fetch_notices()
    new_items = [item for item in notices if item["id"] not in seen]
    selected = new_items[:MAX_RESULTS]

    messages = build_messages(selected, stats, errors)

    if DRY_RUN:
        print("DRY RUN: Telegram delivery and state updates are disabled.")
        for item in selected:
            print(json.dumps(item, ensure_ascii=False))
        write_github_summary(stats, len(selected), errors, True)
        return

    # Send before saving IDs. A failure won't silently mark unsent leads seen.
    for message in messages:
        telegram_send(token, chat_id, message)
        time.sleep(0.4)

    updated_seen = list(state["seen"])
    updated_seen.extend(item["id"] for item in selected)
    save_state(updated_seen)

    print(json.dumps({
        "status": "success",
        "version": VERSION,
        "completed_at": utc_now(),
        "pages_read": stats["pages_read"],
        "records_read": stats["records_read"],
        "relevant_future_deadline_matches":
            stats["matching_open_deadline_notices"],
        "new_notices_sent": len(selected),
        "telegram_messages_sent": len(messages),
        "state_file": str(STATE_PATH),
    }, indent=2))

    write_github_summary(stats, len(selected), errors, False)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"FATAL: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
