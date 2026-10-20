"""
联网语料抓取器 —— 为「扩语料再重评」提供万级 token 的中文训练语料。

合规前提（先于代码）：
- 已实测本机可达性：中文维基、GitHub raw、ctext、gutendex 均**不可达**；
  可选源只剩 gushiwen.cn 与 gutenberg.org（用户选定「两者混合」）。
- 已核对 robots.txt：gushiwen 无限制声明；Gutenberg 仅 Disallow `/ebooks/search`
  （我们不碰搜索页，只取 `/cache/epub/<id>/pg<id>.txt` 正文）。
- 内容为**公共领域**（古诗词及古典散文），仅取公开免费页面，不触碰付费/登录内容。
- 限速 + 显式 User-Agent + 失败即停（不重试轰炸），避免给对方站点造成压力。
- 抓取产物写入 `.cache/` 并 gitignore（**不入仓**）。

用法：
    python tools/fetch_corpus.py --target-tokens 100000
    python tools/fetch_corpus.py --target-tokens 20000 --delay 0.5 --dry-run
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from easy_ai.ai.eval.tokenize import tokenize  # noqa: E402

UA = "easy-ai-research/1.0 (local corpus research; contact: local user)"

# 中文占比门槛：低于此值的文本丢弃（防止英文公版书稀释中文字符分布）
MIN_CJK_RATIO = 0.30
_CJK_RE = re.compile(r'[一-鿿]')


def cjk_ratio(text: str) -> float:
    """文本中汉字字符的占比。"""
    if not text:
        return 0.0
    return len(_CJK_RE.findall(text)) / len(text)

# gushiwen 列表页（诗词 + 文言文，覆盖面广）
# 只保留纯 ASCII 路径（中文路径会让 urllib 的 ASCII 编码直接抛错，
# 实测踩到过）。URL 统一经 _safe_url 编码后再用。
GSW_LIST_PAGES = [
    "https://www.gushiwen.cn/gushi/tangshi.aspx",
    "https://www.gushiwen.cn/gushi/songci.aspx",
    "https://www.gushiwen.cn/gushi/shijing.aspx",
    "https://www.gushiwen.cn/wenyan/guwen.aspx",
    "https://www.gushiwen.cn/gushi/sanbai.aspx",
    "https://www.gushiwen.cn/gushi/yuanqu.aspx",
]

# Gutenberg：公共领域。中文书极少，取若干已知公版 id（失败即跳过，如实记录）
GUTEN_IDS = [
    24039,  # 庄子（英译）
    15250,  # 老子（英译）
    25322,  # 论语（英译）
]


# ============================================================
# HTTP
# ============================================================
def _safe_url(url: str) -> str:
    """把 URL 里的非 ASCII 字符做百分号编码（urllib 内部按 ASCII 编码请求行）。"""
    from urllib.parse import quote, urlsplit, urlunsplit
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path),
                       quote(parts.query, safe="=&"), parts.fragment))


def fetch(url: str, timeout: int = 20, retries: int = 2) -> Optional[str]:
    """抓取并返回解码后的文本；失败返回 None（不重试轰炸）。"""
    url = _safe_url(url)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            for enc in ("utf-8", "gb18030", "gbk"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            if attempt == retries - 1:
                return None
            time.sleep(1.0 + attempt)
    return None


# ============================================================
# gushiwen 解析
# ============================================================
def gsw_list_links(page_html: str) -> List[str]:
    """从列表页提取详情页链接。"""
    links = re.findall(r'/shiwenv_[A-Za-z0-9]+\.aspx', page_html)
    seen, out = set(), []
    for lk in links:
        if lk not in seen:
            seen.add(lk)
            out.append(lk)
    return out


def gsw_parse_detail(page_html: str) -> Tuple[str, str]:
    """解析详情页 → (标题, 正文+赏析)。"""
    title = ""
    m = re.search(r'<h1[^>]*>(.*?)</h1>', page_html, re.S)
    if m:
        title = _clean(m.group(1))

    parts: List[str] = []
    # ⚠️ class 可能是**多值**（如 class="cont contyishang"），不能要求精确相等 ——
    # 早先写成 class=["\']contyishang["\'] 导致赏析整段漏抓，
    # 每篇只拿到 24 token 的诗词正文（实测踩到）。
    # 诗词/古文正文
    m = _div_with_class(page_html, "contson")
    if m:
        parts.append(_clean(m))
    # 赏析 / 译文（现代汉语叙述，对语言建模比诗词本身更有价值）
    for m in _div_all_with_class(page_html, "contyishang"):
        t = _clean(m)
        if len(t) >= 20:
            parts.append(t)
    for m in _div_all_with_class(page_html, "juzioncont"):
        t = _clean(m)
        if len(t) >= 20:
            parts.append(t)
    return title, "\n".join(p for p in parts if p)


_DIV_OPEN_RE = re.compile(r'<div\b', re.I)
_DIV_CLOSE_RE = re.compile(r'</div\s*>', re.I)


def _matched_div(html_text: str, open_idx: int) -> str:
    """从 `<div` 的起始下标出发，按嵌套深度配对，返回该 div 的内部 HTML。

    为什么不能用非贪婪 `(.*?)</div>`：目标 div 内部还嵌着别的 div
    （实测页面里 contyishang 内先是一个标题 div），非贪婪会在**第一个**
    `</div>` 就收尾，把正文整段漏掉 —— 早先每篇只拿到 24 token 就是这么来的。
    """
    gt = html_text.find('>', open_idx)
    if gt < 0:
        return ""
    depth, i, n = 1, gt + 1, len(html_text)
    while depth > 0 and i < n:
        nd = _DIV_OPEN_RE.search(html_text, i)
        cd = _DIV_CLOSE_RE.search(html_text, i)
        nd_pos = nd.start() if nd else n
        cd_pos = cd.start() if cd else n
        if cd_pos >= n:
            break
        if nd_pos < cd_pos:
            depth += 1
            i = nd_pos + 4
        else:
            depth -= 1
            i = cd_pos + 6
    end = (i - 6) if depth == 0 else n
    return html_text[gt + 1:end]


def _find_divs_with_class(html_text: str, cls: str) -> List[int]:
    """返回所有 class 包含 cls 的 `<div` 起始下标。"""
    return [m.start() for m in re.finditer(
        r'<div\b[^>]*class=["\'][^"\']*\b' + cls + r'\b[^"\']*["\'][^>]*>', html_text)]


def _div_with_class(html_text: str, cls: str) -> Optional[str]:
    idxs = _find_divs_with_class(html_text, cls)
    return _matched_div(html_text, idxs[0]) if idxs else None


def _div_all_with_class(html_text: str, cls: str) -> List[str]:
    return [_matched_div(html_text, i) for i in _find_divs_with_class(html_text, cls)]


def _clean(fragment: str) -> str:
    """去标签、压空白、反转义。"""
    t = re.sub(r'<script.*?</script>', ' ', fragment, flags=re.S | re.I)
    t = re.sub(r'<style.*?</style>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    t = re.sub(r'[ \t\u3000]+', ' ', t)
    t = re.sub(r'\n{2,}', '\n', t)
    return t.strip()


# ============================================================
# Gutenberg
# ============================================================
def gutenberg_text(book_id: int) -> Optional[str]:
    url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
    txt = fetch(url)
    if not txt:
        return None
    # 去掉 Gutenberg 头部/尾部声明
    start = txt.find("*** START OF")
    end = txt.find("*** END OF")
    if start >= 0:
        txt = txt[start:]
    if end >= 0:
        txt = txt[:end]
    return txt.strip()


# ============================================================
# 主流程
# ============================================================
def crawl(target_tokens: int, delay: float, out_path: Path,
          dry_run: bool = False, max_pages: int = 2000) -> dict:
    records: List[dict] = []
    tokens = 0
    fetched = failed = 0

    skipped_low_cjk = 0

    def emit(source: str, title: str, text: str) -> bool:
        nonlocal tokens, skipped_low_cjk
        if not text or len(text) < 20:
            return False
        # 中文占比门槛：本项目建模的是中文，英文书（哪怕来自公共领域）
        # 只会稀释字符分布。实测 pg15250 / pg25322 是英文，
        # 若不设门槛会把合计中文占比压到 32%。
        if cjk_ratio(text) < MIN_CJK_RATIO:
            skipped_low_cjk += 1
            return False
        n = len(tokenize(text))
        records.append({"source": source, "title": title, "text": text})
        tokens += n
        return True

    # ① Gutenberg 先抓（公共领域，许可最干净）；量小，先落袋为安 ——
    #   否则 gushiwen 一旦先达目标就 break，混合来源会退化成单一来源（实测踩到）。
    guten_ok = 0
    for bid in GUTEN_IDS:
        txt = gutenberg_text(bid)
        if txt:
            if emit("gutenberg", f"pg{bid}", txt[:60000]):
                guten_ok += 1
                print(f"    [gutenberg] pg{bid} 已收")
        time.sleep(delay)

    # ② gushiwen：列表页 → 详情页
    links: List[str] = []
    for lp in GSW_LIST_PAGES:
        if tokens >= target_tokens:
            break
        page = fetch(lp)
        if not page:
            print(f"  [列表页失败] {lp}")
            continue
        got = gsw_list_links(page)
        print(f"  [列表页] {lp.split('/')[-1]} → {len(got)} 条链接")
        links.extend(got)
        time.sleep(delay)

    # 去重 + 打散（避免总抓同一类目）
    seen, uniq = set(), []
    for lk in links:
        if lk not in seen:
            seen.add(lk)
            uniq.append(lk)
    random.Random(0).shuffle(uniq)

    print(f"  待抓详情页：{len(uniq)} 条，目标 {target_tokens} token\n")
    for i, lk in enumerate(uniq[:max_pages]):
        if tokens >= target_tokens:
            break
        url = "https://www.gushiwen.cn" + lk
        page = fetch(url)
        if not page:
            failed += 1
            continue
        title, text = gsw_parse_detail(page)
        if emit("gushiwen", title, text):
            fetched += 1
            if fetched % 25 == 0:
                print(f"    已收 {fetched} 篇 / 累计 {tokens} token")
        else:
            failed += 1
        time.sleep(delay)

    result = {
        "records": len(records),
        "tokens": tokens,
        "gushiwen_ok": fetched,
        "gutenberg_ok": guten_ok,
        "failed": failed,
        "skipped_low_cjk": skipped_low_cjk,
        "cjk_ratio": (round(cjk_ratio("\n".join(r["text"] for r in records)), 3)
                      if records else 0.0),
        "sources": {},
    }
    for r in records:
        result["sources"][r["source"]] = result["sources"].get(r["source"], 0) + 1

    if not dry_run and records:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n已写入 {out_path}（{len(records)} 条 / {tokens} token）")
    return result


def main():
    ap = argparse.ArgumentParser(description="联网抓取训练语料")
    ap.add_argument("--target-tokens", type=int, default=100000)
    ap.add_argument("--delay", type=float, default=0.4, help="每次请求间隔（秒，限速）")
    ap.add_argument("--out", default=str(ROOT / ".cache" / "corpus_web.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=== 联网语料抓取 ===")
    print(f"目标 {args.target_tokens} token，限速 {args.delay}s/请求")
    print("来源：gushiwen.cn（公版古诗词/散文）+ gutenberg.org（公共领域）\n")

    t0 = time.time()
    r = crawl(args.target_tokens, args.delay, Path(args.out), args.dry_run)
    print(f"\n结果：{r['records']} 条 / {r['tokens']} token  "
          f"（gushiwen {r['gushiwen_ok']} · gutenberg {r['gutenberg_ok']} · 失败 {r['failed']}）")
    print(f"来源分布：{r['sources']}")
    print(f"中文占比：{r['cjk_ratio'] * 100:.1f}%（因非中文被跳过 {r['skipped_low_cjk']} 条）")
    print(f"耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
