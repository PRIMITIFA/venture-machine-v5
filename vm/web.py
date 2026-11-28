"""Plain web fetching: pages, text, sitemaps, trust signals, screenshots (real browser command, Playwright or headless Chrome)."""
import html as htmlmod
import re
import time
import xml.etree.ElementTree as ET

import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def fetch(url, timeout=20, retries=1):
    """Returns dict(url, status, ms, bytes, html, error). Never raises. A network error or a 5xx answer is tried once more
    after a short wait: one bad moment of a rival's server must not turn into 'could not open'."""
    p = _fetch(url, timeout)
    for _ in range(retries):
        if p["status"] and p["status"] < 500:
            break
        time.sleep(4)
        p = _fetch(url, timeout)
    return p


def _fetch(url, timeout=20):
    if not url.startswith("http"):
        url = "https://" + url
    t0 = time.time()
    try:
        r = httpx.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=timeout, follow_redirects=True)
        return {"url": str(r.url), "status": r.status_code, "ms": int((time.time() - t0) * 1000),
                "bytes": len(r.content), "html": r.text, "error": ""}
    except Exception as e:  # network errors are data here, not crashes
        return {"url": url, "status": 0, "ms": int((time.time() - t0) * 1000), "bytes": 0, "html": "", "error": str(e)[:200]}


def text_of(html, limit=8000):
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    t = re.sub(r"\s+", " ", htmlmod.unescape(h)).strip()
    return t[:limit]


def title_of(html):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    return re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip() if m else ""


def links_of(html, base):
    out = []
    for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or ""):
        if href.startswith("/"):
            href = base.rstrip("/") + href
        if href.startswith("http"):
            out.append((href, re.sub(r"(?s)<[^>]+>", "", label).strip()[:80]))
    return out


def blocked(page):
    h = (page.get("html") or "")[:20000].lower()
    return page["status"] in (401, 403, 429, 503) or any(s in h for s in ("captcha", "cf-challenge", "are you a robot", "access denied"))


TRUST = {
    "reviews": r"trustpilot|reviews?\b|testimonial|rated \d|stars?\b",
    "guarantee": r"guarantee|money.back|refund",
    "contact": r"contact us|mailto:|support@|\+\d[\d\s\-()]{7,}",
    "free_sample": r"free (sample|trial|preview|demo|report|check|plan|tier)|try (it )?free|sample report",
    "pricing_visible": r"\$\s?\d|€\s?\d|£\s?\d|pricing|per month|/mo\b",
    "about_page": r"about us|our team|founded",
}
CHECKOUT = {
    "stripe": r"js\.stripe\.com|stripe\.com|checkout\.stripe", "paddle": r"paddle\.com|paddle\.js",
    "lemonsqueezy": r"lemonsqueezy", "paypal": r"paypal\.com", "shopify": r"cdn\.shopify|myshopify",
    "gumroad": r"gumroad", "dodo": r"dodopayments", "chargebee": r"chargebee", "fastspring": r"fastspring",
}


def signals(html):
    h = (html or "").lower()
    return {
        "trust": {k: bool(re.search(p, h)) for k, p in TRUST.items()},
        "checkout": [k for k, p in CHECKOUT.items() if re.search(p, h)],
        "mobile_viewport": 'name="viewport"' in h,
    }


def sitemap(domain, max_children=5):
    """Count URLs and oldest/newest lastmod. Returns dict(found, urls, oldest, newest, source)."""
    base = "https://" + domain.strip("/")
    cands = [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    rb = fetch(base + "/robots.txt", timeout=10)
    cands = re.findall(r"(?im)^sitemap:\s*(\S+)", rb.get("html") or "") + cands
    for c in cands:
        p = fetch(c, timeout=15)
        if p["status"] != 200 or "<" not in p["html"][:200]:
            continue
        urls, mods = [], []
        try:
            root = ET.fromstring(p["html"].encode("utf-8", "ignore"))
        except ET.ParseError:
            continue
        ns = re.match(r"\{.*\}", root.tag)
        ns = ns.group(0) if ns else ""
        if root.tag.endswith("sitemapindex"):
            children = [e.findtext(f"{ns}loc") for e in root.findall(f"{ns}sitemap")][:max_children]
            n_children = len(root.findall(f"{ns}sitemap"))
            for ch in children:
                cp = fetch(ch, timeout=15)
                try:
                    cr = ET.fromstring(cp["html"].encode("utf-8", "ignore"))
                except ET.ParseError:
                    continue
                for u in cr.findall(f"{ns}url"):
                    urls.append(u.findtext(f"{ns}loc"))
                    if u.findtext(f"{ns}lastmod"):
                        mods.append(u.findtext(f"{ns}lastmod")[:10])
            est = len(urls) if n_children <= max_children else int(len(urls) / max(len(children), 1) * n_children)
            return {"found": True, "urls": est, "oldest": min(mods) if mods else "", "newest": max(mods) if mods else "",
                    "source": c, "note": f"index with {n_children} sitemaps" + (" (estimated)" if n_children > max_children else "")}
        for u in root.findall(f"{ns}url"):
            urls.append(u.findtext(f"{ns}loc"))
            if u.findtext(f"{ns}lastmod"):
                mods.append(u.findtext(f"{ns}lastmod")[:10])
        return {"found": True, "urls": len(urls), "oldest": min(mods) if mods else "", "newest": max(mods) if mods else "", "source": c, "note": ""}
    return {"found": False, "urls": 0, "oldest": "", "newest": "", "source": "", "note": "no sitemap"}


SHOT_SIZES = (("desktop", 1366, 900, False), ("mobile", 390, 844, True))


def screenshots(url, out_prefix):
    """Desktop + mobile screenshots of a page. Playwright when installed, else the Chrome/Edge/Chromium already on the
    machine in headless mode, so the rival audit always SEES the pages. Returns list of file paths (maybe empty)."""
    import os
    import subprocess
    from .config import S
    url = url if url.startswith("http") else "https://" + url
    paths = []
    if S.shot_cmd:   # a real browser is the most faithful view, and the only one some rivals let in
        path = f"{out_prefix}-desktop.png"
        try:
            if os.path.exists(path):
                os.remove(path)
            subprocess.run(S.shot_cmd.split() + [url, path], capture_output=True, timeout=90)
        except (subprocess.TimeoutExpired, OSError):
            pass
        if os.path.exists(path) and os.path.getsize(path) > 5000:
            return [path]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            for name, w, h, mobile in SHOT_SIZES:
                ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, user_agent=UA)
                pg = ctx.new_page()
                pg.goto(url, timeout=30000, wait_until="domcontentloaded")
                pg.wait_for_timeout(1500)
                path = f"{out_prefix}-{name}.png"
                pg.screenshot(path=path)
                paths.append(path)
                ctx.close()
            b.close()
        return paths
    except Exception:
        paths = []
    from .pdf import find_browser
    br = find_browser()
    if not br:
        return []
    for name, w, h, _mobile in SHOT_SIZES:
        path = f"{out_prefix}-{name}.png"
        try:
            if os.path.exists(path):
                os.remove(path)
            subprocess.run([br, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", f"--user-agent={UA}",
                            f"--window-size={w},{h}", "--virtual-time-budget=9000", f"--screenshot={path}", url],
                           capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if os.path.exists(path) and os.path.getsize(path) > 5000:
            paths.append(path)
    return paths
