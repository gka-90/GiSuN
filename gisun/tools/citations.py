"""
Citation check: does the page a chatbot answer cites actually contain the number?

Each number goes through three steps (docs/PIPELINE.md, "Checking a number"):

    C1               is there a source?           text only (agents)
    citation check   is the number on that page?  this module, code only, no model
    C2               does it match official data? agents + official statistics APIs

The extension sends the links it finds in the answer (ChatGPT's citation chips) with their
position in the text; `attach_citations` ties each link to the sentence it ends. For a claim
with a number and a link, `check_claim` downloads the page (HTML or PDF), pulls every number
out of its text and looks for the claim's numbers, rounded to the claim's precision
("4.3%" matches 4.27 or 4.30 on the page). No model is involved, so a "found" or "not found"
is never a guess. What it can't tell: whether the number on the page means the same thing
(a page can mention 4.3% for something else). That is C2's job, against official data.

    status   found        every number of the claim appears on a cited page
             not_found    a cited page was read and at least one number is missing from it
             unreachable  no cited page could be read (login, paywall, timeout, scanned PDF)
             no_link      the claim has numbers but no link

    scope    sentence     the links that end the claim's own sentence
             answer       no link on the sentence, so the sources the answer lists were used
                          (ChatGPT's "Sources:" list; its inline citation chips have no link in the page)

The download is cached per URL for the life of the process.
"""

import html
import io
import re
import threading
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (GiSuN citation check; Hamilton College research project)"
TIMEOUT = 5          # seconds per page
MAX_BYTES = 8_000_000
MAX_ANSWER_LINKS = 6  # an answer's source list: open at most this many pages per claim

# A cited site we already query directly: C2 checks that provider first
PROVIDER_DOMAINS = {
    "bls.gov": "bls", "census.gov": "census", "stlouisfed.org": "fred",
    "cdc.gov": "cdc", "worldbank.org": "worldbank", "datacommons.org": "datacommons",
}

_cache: dict[str, dict] = {}
_inflight: dict[str, threading.Event] = {}  # a URL being downloaded: other claims wait for it
_lock = threading.Lock()


# ---- links -> sentences --------------------------------------------------------------------

def provider_for(url: str) -> str | None:
    """'https://www.bls.gov/eag/eag.ny.htm' -> 'bls' (a provider C2 can query), else None."""
    host = urllib.parse.urlparse(url).hostname or ""
    return next((p for d, p in PROVIDER_DOMAINS.items() if host == d or host.endswith("." + d)), None)


def _sentence_spans(text: str, sentences: list[str]) -> list[tuple[int, int]]:
    spans, at = [], 0
    for s in sentences:
        i = text.find(s, at)
        if i < 0:
            i = text.find(s)
        spans.append((i, i + len(s)) if i >= 0 else (-1, -1))
        if i >= 0:
            at = i + len(s)
    return spans


def attach_citations(claims: list[dict], text: str, sentences: list[str], citations: list[dict]) -> list[str]:
    """Give each claim the links that end its sentence: claim["citations"] = [url, ...] and
    claim["cited_providers"] = providers C2 can query. A link belongs to the last sentence that
    starts before it (ChatGPT puts the chip right after the sentence it supports). Returns the
    links that belong to no claim (for example a source list at the end of the answer)."""
    spans = _sentence_spans(text, sentences)
    by_sentence: dict[str, list[str]] = {}
    unused = []
    chips_by_sentence: dict[str, list[str]] = {}
    for c in citations or []:
        url, at = str(c.get("url") or ""), c.get("offset")
        if c.get("chip") and isinstance(at, int):
            # an inline citation chip: no link, but it marks the sentence just before it as cited
            owner = None
            for s_, (a, _b) in zip(sentences, spans):
                if 0 <= a < at:
                    owner = s_
            if owner is not None:
                chips_by_sentence.setdefault(owner, []).append(str(c["chip"]))
            continue
        if not url.startswith(("http://", "https://")) or not isinstance(at, int):
            continue
        owner = None
        for s, (a, _b) in zip(sentences, spans):
            if 0 <= a <= at:
                owner = s
        if owner is None:
            unused.append(url)
        elif url not in by_sentence.setdefault(owner, []):
            by_sentence[owner].append(url)
    claimed = set()
    answer_links = list(dict.fromkeys(str(c.get("url") or "") for c in citations or []
                                      if str(c.get("url") or "").startswith(("http://", "https://"))))
    for claim in claims:
        urls = [u for s, us in by_sentence.items() if s == claim["sentence"] or s in claim["sentence"] for u in us]
        claim["citations"] = urls
        claim["chips"] = [l for s_, ls in chips_by_sentence.items()
                          if s_ == claim["sentence"] or s_ in claim["sentence"] for l in ls]
        # a sentence with no link of its own: the sources the answer lists (ChatGPT's "Sources:" list;
        # its inline citation chips carry no link in the page until they are hovered)
        claim["answer_links"] = [] if urls else answer_links[:MAX_ANSWER_LINKS]
        claim["cited_providers"] = sorted({p for u in (urls or claim["answer_links"]) if (p := provider_for(u))})
        claimed.update(urls)
    unused += [u for us in by_sentence.values() for u in us if u not in claimed]
    return list(dict.fromkeys(unused))


# ---- one source for the whole answer ------------------------------------------------------

SOURCE_LINE_RE = re.compile(r"^[\s*_]*source[\s*_]*:", re.IGNORECASE)   # "Source:" (singular), not "Sources:"


def single_answer_source(sentences: list[str], citations: list[dict]) -> str | None:
    """The sources the answer lists for itself, as one line the C1 agent and check can read.
    Labeling rule (docs/labeling_rules.md, C1): a source list for the whole answer (one source or
    several, as "Source:" lines or links) counts as a source for every number in it. Whether a
    number really appears in those sources is the citation check's job, not C1's."""
    from gisun.tools.attribution import find_attribution
    urls = list(dict.fromkeys(str(c.get("url") or "") for c in citations or []
                              if str(c.get("url") or "").startswith(("http://", "https://"))))
    lines = [s.strip() for s in sentences if SOURCE_LINE_RE.match(s) and find_attribution(s)["names_specific_source"]]
    if len(lines) == 1:
        return lines[0]
    names = [re.sub(r"^\s*sources?\s*[:\-]\s*", "", l, flags=re.I).strip(" .") for l in lines]
    if not names:
        names = urls[:MAX_ANSWER_LINKS]
    if not names:
        return None
    return "Source: " + "; ".join(dict.fromkeys(names))


# ---- pages -> text -------------------------------------------------------------------------

def prime(citations: list[dict]) -> None:
    """Page text the extension already read in the user's browser (sites like bls.gov refuse a
    script but serve a browser): stored as if it had been downloaded here."""
    with _lock:
        for c in citations or []:
            url, text = c.get("url"), c.get("text")
            if url and isinstance(text, str) and text.strip():
                _cache[url] = {"ok": True, "text": text, "via": "browser"}


def readable_reason(reason: str) -> str:
    """'HTTPError: HTTP Error 403: Forbidden' -> 'the site refused access (403)'."""
    r = reason or ""
    for code, say in (("403", "the site refused access (403)"), ("404", "page not found (404): the link may be wrong"),
                      ("401", "needs a login (401)"), ("410", "page removed (410)")):
        if code in r:
            return say
    if "timed out" in r.lower() or "timeout" in r.lower():
        return "the site didn't answer in time"
    if "pypdf" in r:
        return "PDF reader not installed"
    if "no readable text" in r:
        return "no readable text (scanned PDF or a page built by scripts)"
    return "couldn't connect to the site"

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    return html.unescape(" ".join(p.parts))


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader  # optional dependency: without it a PDF is "unreachable"
    return " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def fetch_text(url: str) -> dict:
    """{"ok": True, "text": ...} or {"ok": False, "reason": ...}. Cached per URL, and each URL is
    downloaded once even when several claims ask for it at the same time (an answer's source list
    is shared by every sentence without a link of its own)."""
    with _lock:
        if url in _cache:
            return _cache[url]
        waiting = _inflight.get(url)
        if waiting is None:
            _inflight[url] = threading.Event()
    if waiting is not None:
        waiting.wait(TIMEOUT + 10)
        with _lock:
            return _cache.get(url, {"ok": False, "reason": "download still running"})
    try:
        return _download(url)
    finally:
        with _lock:
            _inflight.pop(url).set()


def _download(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            kind = r.headers.get("Content-Type", "")
            data = r.read(MAX_BYTES)
        if "pdf" in kind or url.lower().split("?")[0].endswith(".pdf"):
            text = pdf_to_text(data)
        else:
            text = html_to_text(data.decode(r.headers.get_content_charset() or "utf-8", "replace"))
        out = {"ok": True, "text": text} if text.strip() else {"ok": False, "reason": "no readable text (scanned PDF or empty page)"}
    except ImportError:
        out = {"ok": False, "reason": "PDF support needs the pypdf package"}
    except Exception as e:
        out = {"ok": False, "reason": f"{type(e).__name__}: {e}"[:200]}
    with _lock:
        _cache[url] = out
    return out


# ---- numbers -------------------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.,])[-−]?\d+(?:\.\d+)?")


def _parse(token: str) -> tuple[float, int] | None:
    """'431,800' -> (431800.0, 0); '4.30' -> (4.3, 2). The second value is the decimals written."""
    t = token.replace(",", "").replace("−", "-")
    try:
        return float(t), (len(t.split(".")[1]) if "." in t else 0)
    except ValueError:
        return None


def numbers_on_page(text: str) -> list[float]:
    return [v for tok in NUMBER.findall(text) if (p := _parse(tok)) for v in [p[0]]]


def claim_numbers(value: str) -> list[tuple[float, int]]:
    """The numbers in a flagged value: '4.3%' -> [(4.3, 1)]; '$2.3M' -> [(2.3, 1)]."""
    return [p for tok in NUMBER.findall(value or "") if (p := _parse(tok))]


def appears(number: tuple[float, int], page: list[float]) -> bool:
    """The number is on the page when a page number, rounded to the claim's precision, equals it."""
    v, dec = number
    return any(round(x, dec) == round(v, dec) for x in page)


# ---- one claim -----------------------------------------------------------------------------

def check_claim(claim: dict, fetch=fetch_text) -> dict | None:
    """The citation check for one claim, or None when the claim has no number to check."""
    values = list(dict.fromkeys(claim.get("checkable_values") or claim.get("stat_values") or []))
    numbers = [(v, n) for v in values for n in claim_numbers(v)]
    if not numbers:
        return None
    urls, scope = claim.get("citations") or [], "sentence"
    if not urls and claim.get("answer_links"):
        urls, scope = claim["answer_links"], "answer"
    if not urls:
        return {"status": "no_link", "scope": None, "pages": []}
    pages, found = [], set()
    for url in urls:
        page = fetch(url)
        if not page["ok"]:
            pages.append({"url": url, "read": False, "reason": page["reason"], "why": readable_reason(page["reason"])})
            continue
        on_page = numbers_on_page(page["text"])
        hits = [v for v, n in numbers if appears(n, on_page)]
        found.update(hits)
        pages.append({"url": url, "read": True, "found": hits})
    if not any(p["read"] for p in pages):
        status = "unreachable"
    elif all(v in found for v, _ in numbers):
        status = "found"
    else:
        status = "not_found"
    return {"status": status, "scope": scope, "values": values,
            "missing": [v for v in values if v not in found], "pages": pages}


# ---- what the user sees per number ---------------------------------------------------------

SOURCE_LINE = {
    "found": "found on the cited page",
    "not_found": "not found on the cited page",
    "unreachable": "the cited page couldn't be opened",
    "no_link": "no link given",
}


def number_check(claim_out: dict) -> dict | None:
    """The two lines the extension shows for a number:
    source   - from the citation check, or from C1 when there is no link
    official - from C2"""
    cc = claim_out.get("citation_check")
    if cc is None:
        return None
    c1 = (claim_out["criteria"].get("C1") or {}).get("decision")
    if cc["status"] != "no_link":
        source = cc["status"]
    elif c1 == "not_met":
        source = "named"           # a source is named in the text, but no link to open
    else:
        source = "none"
    c2 = (claim_out["criteria"].get("C2") or {}).get("decision")
    official = {"not_met": "matches", "met": "conflicts", "undetermined": "unverifiable"}.get(c2, "not_checked")
    warn = source in ("not_found", "none") and official == "conflicts"
    return {"source": source, "scope": cc.get("scope"), "official": official, "warn": warn}
