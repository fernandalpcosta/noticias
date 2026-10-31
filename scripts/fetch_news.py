#!/usr/bin/env python3
"""
Coletor de manchetes do portal "Notícias".

Lê os feeds RSS/Atom de jornais do mundo inteiro, organiza por região,
identifica os assuntos que mais aparecem e grava tudo em data/news.json,
que é o arquivo lido pela página (index.html).

Não precisa de nenhuma biblioteca externa: só Python 3.9+.

Opcional: se a variável de ambiente ANTHROPIC_API_KEY existir (secret do
GitHub), o script também pede ao Claude um "Resumo do dia" em português.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "scripts" / "feeds.json"
OUT_FILE = ROOT / "data" / "news.json"

ITEMS_PER_SOURCE = 8
SUMMARY_MAX_CHARS = 220
USER_AGENT = "Mozilla/5.0 (compatible; NoticiasPortal/1.0; +https://github.com/fernandalpcosta/noticias)"

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


# --------------------------------------------------------------------------- #
# Download e leitura dos feeds
# --------------------------------------------------------------------------- #

def download(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def local(tag: str) -> str:
    """Remove o namespace de uma tag XML: '{http://...}title' -> 'title'."""
    return tag.rsplit("}", 1)[-1].lower()


def child_text(el: ET.Element, *names: str) -> str:
    for child in el:
        if local(child.tag) in names:
            if (child.text or "").strip():
                return child.text.strip()
            # Atom: <link href="..."/>
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return ""


def atom_link(el: ET.Element) -> str:
    alt = ""
    for child in el:
        if local(child.tag) == "link":
            rel = child.attrib.get("rel", "alternate")
            href = child.attrib.get("href", "")
            if rel == "alternate" and href:
                return href
            alt = alt or href
    return alt


def find_image(el: ET.Element) -> str:
    for child in el.iter():
        name = local(child.tag)
        if name in ("content", "thumbnail") and child.attrib.get("url"):
            medium = child.attrib.get("medium", "image")
            ctype = child.attrib.get("type", "image/")
            if medium == "image" or ctype.startswith("image"):
                return child.attrib["url"]
        if name == "enclosure" and child.attrib.get("type", "").startswith("image") and child.attrib.get("url"):
            return child.attrib["url"]
    return ""


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text: str, limit: int | None = None) -> str:
    text = html.unescape(TAG_RE.sub(" ", html.unescape(text or "")))
    text = WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-")
        text = cut + "…"
    return text


def parse_date(value: str) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="minutes")


def parse_feed(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    entries = [el for el in root.iter() if local(el.tag) in ("item", "entry")]
    items = []
    for el in entries:
        is_atom = local(el.tag) == "entry"
        title = clean(child_text(el, "title"))
        link = atom_link(el) if is_atom else child_text(el, "link", "guid")
        summary = child_text(el, "description", "summary", "content", "encoded")
        date = child_text(el, "pubdate", "published", "updated", "date")
        if not title or not link:
            continue
        items.append({
            "title": title,
            "link": link.strip(),
            "summary": clean(summary, SUMMARY_MAX_CHARS),
            "published": parse_date(date),
            "image": find_image(el),
        })
    return items


def fetch_source(src: dict) -> tuple[dict, list[dict], str | None]:
    try:
        items = parse_feed(download(src["url"]))
    except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError, OSError) as exc:
        return src, [], f"{type(exc).__name__}: {exc}"
    # Ordena pelas mais recentes e remove repetidas
    seen, unique = set(), []
    for it in sorted(items, key=lambda i: i["published"] or "", reverse=True):
        key = it["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        # Se o resumo só repete o título, descarta
        if it["summary"].lower().startswith(it["title"].lower()[:60]):
            it["summary"] = ""
        unique.append(it)
    return src, unique[:ITEMS_PER_SOURCE], None


# --------------------------------------------------------------------------- #
# Assuntos em destaque (nomes próprios que mais se repetem entre jornais)
# --------------------------------------------------------------------------- #

STOP = set("""
the a an and or of to in on for with by at from as is are was were be been it its this that these those
after before over under into about amid says said say new news live update updates latest more how why what who
when where will would could can may might not no yes but than then there their they he she his her them our we
you your i me my us up down out off top week day year years today first last two three one world video watch
photos analysis opinion report reports breaking explained how-to
el la los las de del y en un una por para con que se su al es lo como más
le les des du et dans pour sur une est qui pas au aux par
o os as do da dos das em no na nos nas um uma e é com por para ao à que se diz
der die das und im mit von zu den ist ein eine auf für
""".split())

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][\wÀ-ÿ'’\-]+")

# Formas diferentes que significam a mesma coisa
ALIASES = {
    "us": "EUA", "u.s.": "EUA", "usa": "EUA", "eeuu": "EUA", "eua": "EUA", "estados": None,
    "uk": "Reino Unido", "britain": "Reino Unido",
    "trump's": "Trump", "trump": "Trump",
    "israel's": "Israel", "israeli": "Israel",
    "russia's": "Rússia", "russia": "Rússia", "russian": "Rússia", "rusia": "Rússia", "russie": "Rússia", "russland": "Rússia",
    "ukraine": "Ucrânia", "ukrainian": "Ucrânia", "ucrania": "Ucrânia", "ucrânia": "Ucrânia",
    "china's": "China", "chinese": "China", "chine": "China",
    "gaza": "Gaza", "iran": "Irã", "iranian": "Irã", "irán": "Irã",
    "brazil": "Brasil", "brazilian": "Brasil", "brasil": "Brasil",
    "spain": "Espanha", "españa": "Espanha", "spanish": "Espanha",
    "europe": "Europa", "european": "Europa", "eu": "UE",
    "india": "Índia", "indian": "Índia", "japan": "Japão", "japanese": "Japão",
    "france": "França", "french": "França", "germany": "Alemanha", "german": "Alemanha",
    "mexico": "México", "méxico": "México", "venezuela": "Venezuela", "argentina": "Argentina",
    "nato": "OTAN", "otan": "OTAN", "un": None, "onu": "ONU",
    "catalunya": "Catalunha", "cataluña": "Catalunha", "catalonia": "Catalunha",
}


def topic_words(title: str) -> set[str]:
    words = set()
    for raw in WORD_RE.findall(title):
        w = raw.strip("'’-").lower()
        if w in ALIASES:
            if ALIASES[w]:
                words.add(ALIASES[w])
            continue
        if len(w) < 4 or w in STOP:
            continue
        # Só nomes próprios (começam com maiúscula) contam como "assunto"
        if raw[0].isupper():
            words.add(raw.strip("'’-").removesuffix("'s").removesuffix("’s"))
    return words


def trending(sources: list[dict], limit: int = 12) -> list[dict]:
    by_word: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[dict]] = defaultdict(list)
    for src in sources:
        for it in src["items"]:
            for w in topic_words(it["title"]):
                if src["name"] not in by_word[w]:
                    examples[w].append({"title": it["title"], "link": it["link"], "source": src["name"]})
                by_word[w].add(src["name"])
    ranked = sorted(by_word.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out = []
    for word, srcs in ranked:
        if len(srcs) < 2:
            break
        out.append({"topic": word, "sources": len(srcs), "examples": examples[word][:4]})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# Resumo do dia com Claude (opcional)
# --------------------------------------------------------------------------- #

BRIEFING_PROMPT = """Você é editor de um portal de notícias em português do Brasil.
Abaixo estão as manchetes mais recentes de jornais do mundo inteiro (em vários idiomas),
no formato [n] Jornal (região): manchete — resumo.

Escreva o "Resumo do dia": os 6 a 8 assuntos mais importantes, priorizando o que aparece em
vários jornais. Para cada assunto: um título curto em português e 2 a 3 frases explicando o que
aconteceu e por que importa, com suas próprias palavras (nada de copiar frases das fontes).
Seja factual e neutro. Indique os números [n] das manchetes que embasam cada assunto.

Responda APENAS com JSON válido, sem texto antes ou depois, neste formato:
{"intro": "uma frase que resume o dia", "topics": [{"title": "...", "summary": "...", "refs": [1, 5]}]}

Manchetes:
"""


def claude_briefing(sources: list[dict]) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    flat, lines = [], []
    for src in sources:
        for it in src["items"][:5]:
            flat.append({"title": it["title"], "link": it["link"], "source": src["name"]})
            extra = f" — {it['summary']}" if it["summary"] else ""
            lines.append(f"[{len(flat)}] {src['name']} ({src['region']}): {it['title']}{extra}")
    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 2500,
        "messages": [{"role": "user", "content": BRIEFING_PROMPT + "\n".join(lines)}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        text = "".join(b.get("text", "") for b in data.get("content", []))
        text = text[text.find("{"): text.rfind("}") + 1]
        brief = json.loads(text)
    except Exception as exc:  # o portal continua funcionando sem o resumo
        print(f"  ! Resumo do Claude falhou: {exc}", file=sys.stderr)
        return None
    for topic in brief.get("topics", []):
        topic["links"] = [flat[i - 1] for i in topic.pop("refs", []) if isinstance(i, int) and 0 < i <= len(flat)][:4]
    brief["model"] = CLAUDE_MODEL
    return brief


# --------------------------------------------------------------------------- #

def main() -> int:
    config = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    print(f"Coletando {len(config['sources'])} jornais…")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_source, config["sources"]))

    sources, failed = [], []
    for src, items, err in results:
        if err or not items:
            failed.append({"name": src["name"], "error": err or "feed vazio"})
            print(f"  ✗ {src['name']}: {err or 'feed vazio'}")
            continue
        print(f"  ✓ {src['name']}: {len(items)} manchetes")
        sources.append({**src, "items": items})

    if not sources:
        print("Nenhum jornal respondeu — mantendo o arquivo anterior.", file=sys.stderr)
        return 1

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "regions": config["regions"],
        "trending": trending(sources),
        "briefing": claude_briefing(sources),
        "sources": sources,
        "failed": failed,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(s["items"]) for s in sources)
    print(f"Pronto: {total} manchetes de {len(sources)} jornais → {OUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
