#!/usr/bin/env python3
"""
Newsletter de IA — busca novidades, resume com Gemini e envia pro Telegram.
Rodado automaticamente via GitHub Actions (ver .github/workflows/newsletter.yml)
"""

import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

# ============ CONFIG ============

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Janela de tempo: pega notícias dos últimos N dias (semanal = 7)
DAYS_WINDOW = int(os.environ.get("DAYS_WINDOW", "7"))

RSS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
    # A Anthropic não publica feed oficial — este é mantido pela comunidade (taobojlen/anthropic-rss-feed)
    "Anthropic News": "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Hacker News (AI)": "https://hnrss.org/newest?q=AI+OR+LLM+OR+%22large+language+model%22",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
    "MIT Technology Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
    # Fontes em português (BR) — o resto é em inglês, o Gemini traduz na hora de resumir de qualquer forma
    "Tecnoblog (IA)": "https://tecnoblog.net/tema/inteligencia-artificial/feed/",
    "MIT Technology Review Brasil": "https://mittechreview.com.br/feed/",
}

# ============ HELPERS ============


def fetch_url(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ai-newsletter-bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_date(raw):
    """Aceita pubDate RFC-2822 (RSS) ou <updated> ISO-8601 (Atom). Retorna datetime aware ou None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_rss(xml_bytes, source_name, cutoff):
    """Parse RSS/Atom feed, return list of dicts with recent items."""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    # RSS 2.0
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = item.findtext("pubDate") or ""
        desc = (item.findtext("description") or "").strip()
        items.append({"title": title, "link": link, "date": pub_date, "desc": desc, "source": source_name})

    # Atom fallback
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns):
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            pub_date = entry.findtext("a:published", namespaces=ns) or entry.findtext("a:updated", namespaces=ns) or ""
            desc = (entry.findtext("a:summary", namespaces=ns) or "").strip()
            items.append({"title": title, "link": link, "date": pub_date, "desc": desc, "source": source_name})

    # Só o que caiu dentro da janela (item sem data legível fica, pra não perder notícia)
    recentes = []
    for it in items:
        dt = parse_date(it["date"])
        if dt is None or dt >= cutoff:
            recentes.append(it)

    return recentes[:15]  # limita por fonte pra não sobrecarregar


def collect_news():
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_WINDOW)
    all_items = []
    for name, url in RSS_FEEDS.items():
        try:
            raw = fetch_url(url)
            items = parse_rss(raw, name, cutoff)
            all_items.extend(items)
            print(f"[ok] {name}: {len(items)} itens")
        except Exception as e:
            print(f"[erro] {name}: {e}")
        time.sleep(0.5)
    return all_items


def fetch_rankings():
    """Puxa um snapshot simples de ranking de modelos (Artificial Analysis / OpenRouter)."""
    rankings_text = ""
    try:
        raw = fetch_url("https://openrouter.ai/api/v1/models")
        data = json.loads(raw)
        models = data.get("data", [])
        # Ordena por contexto/preço como proxy simples; ideal seria puxar "trending" real
        top = models[:10]
        lines = [f"- {m.get('name', m.get('id'))}" for m in top]
        rankings_text = "Modelos disponíveis no OpenRouter (amostra):\n" + "\n".join(lines)
    except Exception as e:
        print(f"[erro] rankings: {e}")
    return rankings_text


# ============ SUMMARIZE WITH GEMINI ============


def build_newsletter(news_items, rankings_text):
    raw_dump = "\n\n".join(
        f"Fonte: {it['source']}\nTítulo: {it['title']}\nLink: {it['link']}\nResumo original: {it['desc'][:300]}"
        for it in news_items
    )

    prompt = f"""Você vai montar uma newsletter curta em português (Brasil), estilo WhatsApp/Telegram,
sobre as principais novidades de Inteligência Artificial das últimas {DAYS_WINDOW * 24} horas.

Use SOMENTE as informações abaixo (não invente notícias). Selecione as notícias mais relevantes
(novos modelos, lançamentos de API, mudanças de ranking, fusões/aquisições, ferramentas novas) —
normalmente entre 3 e 10, dependendo de quanta coisa relevante saiu no dia. Se não tiver nada relevante,
diga isso em uma frase só, sem forçar notícia fraca.
Ignore itens irrelevantes ou repetidos. Para cada notícia: título curto, 1-2 linhas de resumo, e o link.
Agrupe por categoria se fizer sentido (ex: "Novos Modelos", "APIs e Ferramentas", "Rankings").

Formate em Markdown compatível com Telegram (use *negrito*, evite headers ### que o Telegram não renderiza).
Comece com um título tipo "🤖 Newsletter IA — {datetime.now().strftime('%d/%m/%Y')}".
Seja direto, sem enrolação.

DADOS DE RANKINGS/MODELOS DISPONÍVEIS:
{rankings_text}

NOTÍCIAS BRUTAS COLETADAS:
{raw_dump}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 2000},
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini API {e.code}: {e.read().decode(errors='replace')}") from None

    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


# ============ SEND TO TELEGRAM ============


def _post_telegram(url, chat_id, chunk, parse_mode):
    payload = {
        "chat_id": chat_id,
        "text": chunk,
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Telegram devolve 400 quando o Markdown está malformado — devolve o corpo pra decidir o fallback
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}


def send_telegram(text, chat_id, bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # Telegram limita 4096 caracteres por mensagem — quebra se precisar
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)] or [text]
    for chunk in chunks:
        result = _post_telegram(url, chat_id, chunk, "Markdown")
        if not result.get("ok"):
            # Markdown malformado (ou quebrado no meio pelo chunk) não pode custar a mensagem inteira:
            # reenvia como texto puro.
            print(f"[aviso telegram] Markdown recusado ({result.get('description')}), reenviando sem formatação")
            result = _post_telegram(url, chat_id, chunk, None)
            if not result.get("ok"):
                print(f"[erro telegram] {result}")
        time.sleep(1)


# ============ MAIN ============


def main():
    print("Coletando notícias...")
    news = collect_news()
    print(f"Total de itens coletados: {len(news)}")
    for it in news:
        print(f"  - [{it['source']}] {it['title']} | {it['link']}")

    print("Coletando rankings...")
    rankings = fetch_rankings()

    if not news:
        print("Nenhuma notícia coletada, abortando.")
        return

    print("Gerando newsletter com Gemini...")
    newsletter_text = build_newsletter(news, rankings)

    print("Enviando pro Telegram...")
    send_telegram(newsletter_text, TELEGRAM_CHAT_ID, TELEGRAM_BOT_TOKEN)

    print("Concluído.")


if __name__ == "__main__":
    main()
