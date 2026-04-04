import re
import html2text
from bs4 import BeautifulSoup, Tag

TOKENS_PER_CHAR = 0.25  # 4 chars per token


class MarkdownExtractor:
    def __init__(self, html: str, base_url: str = ""):
        self.soup = BeautifulSoup(html, "html.parser")
        self.base_url = base_url

    @property
    def title(self) -> str:
        t = self.soup.find("title")
        return t.get_text(strip=True) if t else ""

    def to_markdown(
        self,
        selector: str | None = None,
        strip_selectors: list[str] = (),
        include_links: bool = True,
        include_images: bool = False,
    ) -> str:
        for tag in self.soup(["script", "style", "noscript"]):
            tag.decompose()

        for sel in strip_selectors:
            for el in self.soup.select(sel):
                el.decompose()

        root: Tag = self.soup
        if selector:
            el = self.soup.select_one(selector)
            if el:
                root = el

        h = html2text.HTML2Text(baseurl=self.base_url)
        h.ignore_links = not include_links
        h.ignore_images = not include_images
        h.ignore_emphasis = False
        h.body_width = 0
        h.unicode_snob = True
        h.mark_code = True
        h.skip_internal_links = True

        md = h.handle(str(root))
        md = re.sub(r'\n{3,}', '\n\n', md)
        return md.strip()


def apply_strip_lines(markdown: str, patterns: list[str]) -> str:
    if not patterns:
        return markdown
    compiled = [re.compile(p) for p in patterns if _valid_re(p)]
    if not compiled:
        return markdown
    lines = markdown.splitlines()
    return "\n".join(
        line for line in lines
        if not any(rx.search(line) for rx in compiled)
    )


def _valid_re(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)')


def extract_toc(markdown: str) -> list[dict]:
    lines = markdown.splitlines()
    toc = []
    for i, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            toc.append({"level": len(m.group(1)), "title": m.group(2).strip(),
                        "start_line": i, "end_line": len(lines)})
    for i in range(len(toc) - 1):
        toc[i]["end_line"] = toc[i + 1]["start_line"] - 1
    return toc


def read_lines(markdown: str, start: int, end: int) -> str:
    lines = markdown.splitlines()
    total = len(lines)
    start = max(1, start)
    end = min(total, end)
    return "\n".join(f"{i:4}  {lines[i-1]}" for i in range(start, end + 1))


CODE_BLOCK_RE = re.compile(r'(?m)^```([a-zA-Z0-9_+.-]*)')
SYMBOL_RE = re.compile(r'`([A-Za-z_][A-Za-z0-9_]{1,50})`')


def count_code_blocks(markdown: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in CODE_BLOCK_RE.finditer(markdown):
        lang = m.group(1).lower() or "unknown"
        counts[lang] = counts.get(lang, 0) + 1
    return counts


def extract_symbols(markdown: str, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    result = []
    for m in SYMBOL_RE.finditer(markdown):
        sym = m.group(1)
        if sym not in seen:
            seen.add(sym)
            result.append(sym)
        if len(result) >= limit:
            break
    return result


def grep_markdown(
    markdown: str,
    pattern: str,
    context_lines: int = 2,
    ignore_case: bool = False,
    max_matches: int = 50,
) -> str:
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        return f"Invalid pattern: {e}\n"

    lines = markdown.splitlines()
    total = len(lines)
    match_idx = [i for i, ln in enumerate(lines) if rx.search(ln)]

    if not match_idx:
        return f"no matches for {pattern!r} in {total} lines\n"

    truncated = len(match_idx) > max_matches
    shown = match_idx[:max_matches]

    out = [f"{len(match_idx)} match{'es' if len(match_idx) != 1 else ''} "
           f"for {pattern!r} in {total} lines"
           + (f" (showing first {max_matches})" if truncated else "") + "\n"]

    prev_end = -1
    for idx in shown:
        start = max(0, idx - context_lines)
        end = min(total - 1, idx + context_lines)
        if prev_end >= 0 and start > prev_end + 1:
            out.append("--")
        print_from = max(start, prev_end + 1)
        for i in range(print_from, end + 1):
            marker = "*" if i == idx else " "
            out.append(f"{i+1:4}{marker} {lines[i]}")
        prev_end = end

    if truncated:
        out.append(f"--\n[{len(match_idx) - max_matches} more matches — narrow pattern or use /fetch/lines]")

    return "\n".join(out) + "\n"


def paginate(text: str, offset: int, max_tokens: int | None) -> tuple[str, bool, int]:
    if max_tokens is None:
        return text, False, len(text)

    char_limit = int(max_tokens / TOKENS_PER_CHAR)
    start = offset
    end = start + char_limit

    if end >= len(text):
        return text[start:], False, len(text)

    chunk = text[start:end]
    last_nl = chunk.rfind('\n')
    if last_nl > char_limit // 2:
        chunk = chunk[:last_nl]
        end = start + last_nl

    return chunk, True, end
