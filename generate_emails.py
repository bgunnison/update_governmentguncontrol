"""
Generate topic email lists using OpenAI with minimal configuration.

This module reads defaults from app_settings.GENERATE_SETTINGS and
personal.py (for WEBSITE_TOPICS and OPENAI_API_KEY). It performs an
optional curated web search to obtain real, validated URLs and asks the
model to summarize those sources. The app then wraps the output into the
required email-list format, adding Source: URLs itself to avoid AI
hallucinated links.

Key behavior
- Curate mode (default): Searches the web, validates links (HEAD 2xx/3xx),
  and fetches titles/descriptions. The AI only summarizes; it does not
  invent URLs. The app injects the sources in the final output.
- Logging: JSONL file with request, response, validation, and write events.
- Low cost defaults: attempts=1, num=5, temp=0.2, min_ok=3.
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

import requests

try:
    from personal import WEBSITE_TOPICS, OPENAI_API_KEY
except Exception:
    WEBSITE_TOPICS = []
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

EMAIL_SEPARATOR = "---EMAIL_SEPARATOR---"


def ensure_emails_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def build_prompt(topic_name: str, num_entries: int) -> str:
    return (
        "You are researching gun control in 2026.\n"
        f"Category: {topic_name}\n\n"
        "Research guidance:\n"
        "- Perform a general web search for recent articles, reports, and official sources relevant to this category.\n"
        "- Use diverse, reputable, and publicly accessible sources (major news outlets, .gov/.edu, research orgs). Avoid paywalls.\n"
        "- Prefer primary sources or official data where applicable.\n"
        "- Provide at least {n} distinct, noteworthy items with concise summaries and include 1–2 credible source links per item.\n".format(n=num_entries)
    )


def call_openai_chat(api_key: str, model: str, system_msg: str, user_msg: str, temperature: float = 0.2) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def write_topic_file(out_dir: str, topic_name: str, content: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_topic = topic_name.lower().replace(" ", "_")
    out_path = os.path.join(out_dir, f"{safe_topic}_{ts}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")
    return out_path


def split_entries(content: str) -> List[str]:
    parts = [p.strip() for p in content.split(EMAIL_SEPARATOR)]
    return [p for p in parts if p]


def entry_has_source_link(entry: str) -> bool:
    for line in entry.splitlines():
        if re.match(r"(?i)^\s*Source:\s+https?://\S+", line.strip()):
            return True
    return re.search(r"https?://\S+", entry) is not None


def sanitize_url(u: str) -> str:
    """Trim trailing punctuation or brackets often stuck to markdown links."""
    if not u:
        return u
    # Strip common trailing chars: ) ] } . , ; : ' " >
    while u and u[-1] in ")]}.,;:'\">":
        u = u[:-1]
    return u


def extract_urls(text: str) -> List[str]:
    # Stop at whitespace or common closing punctuation/brackets
    raw = re.findall(r"https?://[^\s\]\)\}>\'\"<>]+", text)
    # Sanitize and dedupe preserving order
    seen = set()
    urls: List[str] = []
    for r in raw:
        u = sanitize_url(r)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def _strip_model_disclaimer(text: str) -> str:
    """Remove common AI capability disclaimers and knowledge-cutoff notes.

    This is a lightweight filter to prevent lines like:
    - "As of my last update in ..."
    - "I cannot perform live web searches ..."
    - "As an AI language model ..."
    from appearing in the wrapped content.
    """
    patterns = [
        r"(?i)as of my last update",
        r"(?i)as an ai",
        r"(?i)i cannot (perform live web searches|browse|access current articles)",
        r"(?i)i can't (perform live web searches|browse|access current articles)",
        r"(?i)my knowledge cutoff",
        r"(?i)i do not have browsing capability",
    ]
    lines = text.splitlines()
    filtered = []
    for ln in lines:
        if any(re.search(p, ln) for p in patterns):
            continue
        filtered.append(ln)
    # Remove leading blank lines
    while filtered and not filtered[0].strip():
        filtered.pop(0)
    return "\n".join(filtered).strip()


def _strip_leading_bullet_or_number(line: str) -> str:
    return re.sub(r"^\s*(?:\d+[\)\.:]|[-*•])\s*", "", line).strip()


def split_candidate_items(raw: str) -> List[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if len(blocks) >= 2:
        return blocks
    lines = raw.splitlines()
    starts = []
    for idx, ln in enumerate(lines):
        if re.match(r"^\s*(?:\d+[\)\.:]|[-*•])\s+", ln):
            starts.append(idx)
    if not starts:
        return [raw.strip()] if raw.strip() else []
    starts.append(len(lines))
    items = []
    for i in range(len(starts) - 1):
        chunk = "\n".join(lines[starts[i]:starts[i+1]]).strip()
        if chunk:
            items.append(chunk)
    return items


def wrap_into_email_list(topic_name: str, raw_content: str, expected_count: int, curated_sources: List[Dict] | None = None) -> str:
    candidates = split_candidate_items(raw_content)[:expected_count]
    entries: List[str] = []
    for i, item in enumerate(candidates):
        if not item:
            continue
        lines = [ln for ln in item.splitlines() if ln.strip()]
        if not lines:
            continue
        first = _strip_leading_bullet_or_number(lines[0])
        subject = first[:100].rstrip() + ("…" if len(first) > 100 else "")
        body_lines = []
        source_line_pattern = re.compile(
            r"^\s*(?:[-*]|\d+[\).])?\s*sources?\s*[:\-]",
            re.IGNORECASE,
        )
        r"""
        source_line_pattern = re.compile(r"(?i)^\s*(?:[-*•–—]|\d+[\).])?\s*sources?\s*[:\-]|
                                           (?i)sources?\s*[:\-].*https?://",
                                           re.VERBOSE)
        """
        for ln in lines[1:]:
            # Drop explicit 'Source:' lines (with optional bullet) or lines clearly listing sources with URLs
            if source_line_pattern.search(ln):
                continue
            body_lines.append(ln)
        body = "\n".join(body_lines).strip()

        source_lines: List[str] = []
        if curated_sources and i < len(curated_sources):
            u = curated_sources[i].get("url")
            if u:
                source_lines.append(f"Source: {u}")
        else:
            urls = extract_urls(item)
            for u in urls:
                source_lines.append(f"Source: {u}")
                if len(source_lines) >= 2:
                    break

        entry_lines = [f"**{subject}**", f"[category {topic_name}]" ]
        if body:
            entry_lines.append(body)
        entry_lines.extend(source_lines)
        entries.append("\n".join(entry_lines).strip())

    return f"\n{EMAIL_SEPARATOR}\n".join(entries)


def analyze_entries(content: str) -> Dict:
    entries = split_entries(content)
    missing = [i for i, e in enumerate(entries) if not entry_has_source_link(e)]
    return {
        "entries": entries,
        "count": len(entries),
        "missing_sources_indices": missing,
        "missing_sources_count": len(missing),
    }


# --- Curated search utilities to reduce hallucinated links ---

def _head_ok(url: str, timeout: float = 8.0) -> bool:
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        return 200 <= r.status_code < 400
    except Exception:
        return False


def _get_title_desc(url: str, timeout: float = 10.0) -> tuple[str, str]:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code >= 400:
            return "", ""
        html = r.text
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else ""
        m_desc = re.search(r"<meta[^>]+name=['\"]description['\"][^>]*content=['\"](.*?)['\"][^>]*>", html, re.IGNORECASE)
        desc = re.sub(r"\s+", " ", m_desc.group(1)).strip() if m_desc else ""
        return title, desc
    except Exception:
        return "", ""


def _ddg_fallback_html(query: str, max_results: int = 10) -> List[Dict]:
    try:
        params = {"q": query}
        resp = requests.post("https://duckduckgo.com/html/", data=params, timeout=12)
        html = resp.text
        urls = re.findall(r"<a[^>]+class=\"result__a[^\"]*\"[^>]+href=\"(https?://[^\"]+)\"", html)
        out: List[Dict] = []
        for u in urls:
            out.append({"href": u, "title": ""})
            if len(out) >= max_results:
                break
        return out
    except Exception:
        return []


def search_ddg(query: str, max_results: int = 10) -> List[Dict]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
        out: List[Dict] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                out.append({"href": r.get("href"), "title": r.get("title", "")})
        return out
    except Exception:
        return _ddg_fallback_html(query, max_results=max_results)


def curate_sources_for_topic(topic: str, target: int, max_query_results: int = 12) -> List[Dict]:
    query = f"{topic} gun control site:.gov OR site:.edu OR site:news OR (gun policy research)"
    raw = search_ddg(query, max_results=max_query_results)
    seen = set()
    curated: List[Dict] = []
    for r in raw:
        url = (r.get("href") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if not _head_ok(url):
            continue
        title, desc = _get_title_desc(url)
        curated.append({"url": url, "title": title, "desc": desc})
        if len(curated) >= target:
            break
    return curated


def generate_with_settings(cfg: dict):
    """Generate topic email files using a dict of settings.

    cfg keys:
    - topics: list[str] | None
    - out: str
    - model: str
    - num: int
    - min_ok: int
    - attempts: int
    - temp: float
    - api_key: str | None
    - gen_log: str
    - curate: bool
    - results: int
    """
    out_dir = cfg.get("out", "emails")
    model = cfg.get("model", "gpt-4o-mini")
    num = int(cfg.get("num", 5))
    min_ok = int(cfg.get("min_ok", 0))
    attempts = int(cfg.get("attempts", 1))
    temp = float(cfg.get("temp", 0.2))
    api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", OPENAI_API_KEY)
    gen_log = cfg.get("gen_log", "emails/generate_log.jsonl")
    curate = bool(cfg.get("curate", True))
    results = int(cfg.get("results", 12))

    if not api_key:
        print("Error: OPENAI_API_KEY not set (env or personal.py)")
        sys.exit(1)

    ensure_emails_dir(out_dir)

    topics_cfg = cfg.get("topics")
    topics = WEBSITE_TOPICS or []
    if topics_cfg:
        names = set(t.lower() for t in topics_cfg)
        topics = [t for t in topics if (t if isinstance(t, str) else t.get("name", "")).lower() in names]

    if not topics:
        print("No topics found. Ensure WEBSITE_TOPICS is defined in personal.py or set GENERATE_SETTINGS['topics'].")
        sys.exit(1)

    system_msg = (
        "You are a helpful research and writing assistant. Write concise, factual summaries with sources. "
        "Do not include meta commentary, disclaimers, knowledge-cutoff notes, or statements about browsing capabilities."
    )

    def append_gen_log(event: str, **fields):
        path = Path(out_dir) / Path(gen_log) if not Path(gen_log).is_absolute() else Path(gen_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rec = {"ts": ts, "event": event}
        rec.update(fields)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    for t in topics:
        name = t if isinstance(t, str) else (t.get("name") or str(t))
        print(f"Generating: {name} ...")

        curated_list: List[Dict] | None = None
        if curate:
            print(f"Curating sources for {name} ...")
            curated_list = curate_sources_for_topic(name, target=num, max_query_results=results)
            append_gen_log("curated_sources", topic=name, count=len(curated_list or []), sources=curated_list or [])

        user_msg = build_prompt(name, num)
        if curated_list:
            helper_lines = [
                "Summarize the following sources (1–2 sentences each).",
                "Do not invent URLs or sources. Use only these items.",
                "Separate items with blank lines. No preambles or disclaimers.",
                "",
            ]
            for s in curated_list:
                title = s.get("title") or "(no title)"
                desc = s.get("desc") or ""
                url = s.get("url") or ""
                helper_lines.append(f"- {title} | {desc} | {url}")
            user_msg += "\n" + "\n".join(helper_lines)

        attempt = 0
        content = ""
        while attempt < attempts:
            attempt += 1
            try:
                print("Contacting AI with prompt:\n" + user_msg + "\n")
                append_gen_log(
                    "request",
                    topic=name,
                    attempt=attempt,
                    model=model,
                    temperature=temp,
                    target_num=num,
                    prompt=user_msg,
                )
                t0 = time.time()
                raw = call_openai_chat(api_key, model, system_msg, user_msg, temperature=temp)
                dt = time.time() - t0
                print(f"Got response in {dt:.2f} seconds from AI.\n" + raw + "\n")
                append_gen_log(
                    "response",
                    topic=name,
                    attempt=attempt,
                    duration_sec=round(dt, 2),
                    chars=len(raw),
                    response=raw,
                )
                # Remove common capability disclaimers if present
                cleaned = _strip_model_disclaimer(raw)
                if cleaned != raw:
                    append_gen_log("response_cleaned", topic=name, attempt=attempt)
                content = wrap_into_email_list(name, cleaned, num, curated_sources=curated_list)
            except Exception as e:
                print(f"Attempt {attempt} failed for {name}: {e}")
                append_gen_log("api_error", topic=name, attempt=attempt, error=str(e))
                if attempt >= attempts:
                    break
                time.sleep(1.0)
                continue

            if EMAIL_SEPARATOR not in content:
                print(f"Attempt {attempt}: could not construct entries for {name}; retrying...")
                append_gen_log("wrap_failed", topic=name, attempt=attempt)
                time.sleep(0.5)
                continue

            threshold = min_ok if min_ok > 0 else num
            analysis = analyze_entries(content)
            count = analysis["count"]
            enough = count >= threshold
            valid_links = analysis["missing_sources_count"] == 0

            if not (enough and valid_links):
                if not enough and not valid_links:
                    reason = f"wrong count ({count}/{num}) and missing sources in indices {analysis['missing_sources_indices']}"
                elif not enough:
                    reason = f"wrong count ({count}/{num})"
                else:
                    reason = f"missing sources in indices {analysis['missing_sources_indices']}"
                print(f"Attempt {attempt}: validation failed for {name} ({reason}); retrying...")
                append_gen_log(
                    "validation_failed",
                    topic=name,
                    attempt=attempt,
                    count=count,
                    target=num,
                    min_ok=threshold,
                    missing_sources_indices=analysis["missing_sources_indices"],
                )
                user_msg += (
                    "\nReminder: Provide at least {n} distinct items with concise summaries "
                    "and include 1–2 credible http(s) source links per item.".format(n=num)
                )
                time.sleep(0.5)
                continue

            append_gen_log("validation_passed", topic=name, attempt=attempt, count=count)
            break

        if not content:
            print(f"Failed to generate content for {name}; skipping.")
            continue

        path = write_topic_file(out_dir, name, content)
        append_gen_log("written", topic=name, path=str(path))
        print(f"Success: {name} entries={analyze_entries(content)['count']}; wrote {path}")
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        from app_settings import GENERATE_SETTINGS
    except Exception:
        print("Warning: app_settings.py missing; using internal defaults.")
        GENERATE_SETTINGS = {
            "topics": None,
            "out": "emails",
            "model": "gpt-4o-mini",
            "num": 5,
            "min_ok": 3,
            "attempts": 1,
            "temp": 0.2,
            "api_key": None,
            "gen_log": "emails/generate_log.jsonl",
            "curate": True,
            "results": 12,
        }
    generate_with_settings(GENERATE_SETTINGS)
