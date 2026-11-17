#!/usr/bin/env python3
"""Build a retail-grade Apple Books Read-Aloud Fixed-Layout EPUB3 with:
- Full front matter (Cover, Title Page, Copyright & Terms, Interactive Table of Contents)
- 12 modernized chapters with framed Victorian etching illustrations
- Back matter (About This Edition & Colophon)
- Complete EPUB3 nav.xhtml (in spine + manifest) + EPUB2 toc.ncx compatibility
- Two-level (sentence + word) SMIL highlighting with -120ms visual lead compensation
"""

import argparse
import difflib
import html
import json
import math
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

PAGE_W = 768
PAGE_H = 1024
MAX_LINES_PER_PAGE = 28.0
CHARS_PER_LINE = 68
LEAD_TICKS = 800_000  # 80ms visual lead compensation


def format_smil_time(ticks_100ns: int) -> str:
    total_ms = max(0, round(ticks_100ns / 10_000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def normalize_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_markdown_blocks(md_text: str):
    lines = md_text.strip().splitlines()
    title = "Chapter"
    blocks = []
    para_buf = []
    quote_buf = []

    def flush_para():
        if para_buf:
            blocks.append(("p", " ".join(para_buf).strip()))
            para_buf.clear()

    def flush_quote():
        if quote_buf:
            blocks.append(("blockquote", "\n".join(quote_buf).strip()))
            quote_buf.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and title == "Chapter":
            title = stripped[2:].strip()
            continue
        if stripped.startswith(">"):
            flush_para()
            quote_buf.append(stripped[1:].strip())
        elif stripped == "":
            flush_para()
            flush_quote()
        elif stripped.startswith("## "):
            flush_para()
            flush_quote()
            blocks.append(("h2", stripped[3:].strip()))
        else:
            flush_quote()
            para_buf.append(stripped)

    flush_para()
    flush_quote()
    return title, blocks


def render_inline_sentences_and_words(
    text: str, sent_counter: list, word_counter: list, word_list: list
) -> str:
    parts = re.split(r"(?<=[.!?\"”’)])\s+", text.strip())
    rendered_sents = []

    for sent in parts:
        if not sent:
            continue
        sent_counter[0] += 1
        sid = f"s{sent_counter[0]:04d}"

        segments = re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", sent)
        seg_out = []
        for seg in segments:
            if not seg:
                continue
            tag = None
            inner = seg
            if seg.startswith("**") and seg.endswith("**") and len(seg) > 4:
                tag = "strong"
                inner = seg[2:-2]
            elif seg.startswith("*") and seg.endswith("*") and len(seg) > 2:
                tag = "em"
                inner = seg[1:-1]

            tokens = re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|[^\w\s]+|\s+", inner)
            tok_html = []
            for tok in tokens:
                if re.match(r"^[A-Za-z0-9]", tok):
                    word_counter[0] += 1
                    wid = f"w{word_counter[0]:05d}"
                    word_list.append({"id": wid, "sid": sid, "text": tok})
                    tok_html.append(f'<span class="word" id="{wid}">{html.escape(tok)}</span>')
                else:
                    tok_html.append(html.escape(tok))
            joined = "".join(tok_html)
            seg_out.append(f"<{tag}>{joined}</{tag}>" if tag else joined)

        rendered_sents.append(f'<span class="sent" id="{sid}">{"".join(seg_out)}</span>')

    return " ".join(rendered_sents)


def estimate_block_lines(tag: str, raw: str) -> float:
    if tag == "h1":
        return 2.0
    if tag == "h2":
        return 2.0
    if tag == "illus":
        return 13.5
    if tag == "blockquote":
        lines = raw.splitlines()
        return sum(max(1, math.ceil(len(ln) / (CHARS_PER_LINE - 6))) for ln in lines) + 1.0
    return max(1, math.ceil(len(raw) / CHARS_PER_LINE)) + 0.45


def split_paragraph_to_fit(raw: str, remaining_lines: float):
    sentences = re.split(r"(?<=[.!?\"”’)])\s+", raw.strip())
    fit = []
    rest = []
    used = 0.0
    for i, s in enumerate(sentences):
        cand = " ".join(fit + [s])
        cand_lines = max(1, math.ceil(len(cand) / CHARS_PER_LINE)) + 0.45
        if cand_lines <= remaining_lines or (
            not fit and remaining_lines >= 3.0 and len(sentences) == 1 and cand_lines <= remaining_lines + 0.5
        ):
            fit.append(s)
            used = cand_lines
        else:
            rest = sentences[i:]
            break
    return (" ".join(fit) if fit else None), (" ".join(rest) if rest else None), used


def split_blockquote_to_fit(raw: str, remaining_lines: float):
    """Split a multi-line blockquote/poem at line boundaries to fit remaining_lines cleanly."""
    lines = raw.splitlines()
    # Account for 1.0 line margin/padding overhead
    max_q_lines = int(remaining_lines - 1.0)
    if max_q_lines < 2:
        return None, raw, 0.0
    fit_lines = []
    rest_lines = []
    used = 1.0
    for i, ln in enumerate(lines):
        ln_cost = max(1, math.ceil(len(ln) / (CHARS_PER_LINE - 6))) if ln.strip() else 0.7
        if used + ln_cost <= remaining_lines or not fit_lines:
            if used + ln_cost > remaining_lines:
                rest_lines = lines[i:]
                break
            fit_lines.append(ln)
            used += ln_cost
        else:
            rest_lines = lines[i:]
            break
    if not fit_lines:
        return None, raw, 0.0
    return "\n".join(fit_lines).strip(), ("\n".join(rest_lines).strip() if rest_lines else None), used


def paginate_blocks(title: str, blocks: list, has_illus: bool = False) -> list:
    queue = [("h1", title)]
    if has_illus:
        queue.append(("illus", ""))
    queue.extend(blocks)

    pages = []
    cur_page = []
    cur_lines = 0.0

    idx = 0
    while idx < len(queue):
        tag, raw = queue[idx]
        blines = estimate_block_lines(tag, raw)
        if cur_lines + blines <= MAX_LINES_PER_PAGE:
            cur_page.append((tag, raw))
            cur_lines += blines
            idx += 1
        else:
            rem = MAX_LINES_PER_PAGE - cur_lines
            if tag == "p" and rem >= 2.5:
                fit_txt, rest_txt, used_lines = split_paragraph_to_fit(raw, rem)
                if fit_txt:
                    cur_page.append(("p", fit_txt))
                    cur_lines += used_lines
                    if rest_txt:
                        queue[idx] = ("p", rest_txt)
                    else:
                        idx += 1
                    pages.append(cur_page)
                    cur_page = []
                    cur_lines = 0.0
                    continue
            if tag == "blockquote" and rem >= 4.0:
                fit_q, rest_q, used_q = split_blockquote_to_fit(raw, rem)
                if fit_q:
                    cur_page.append(("blockquote", fit_q))
                    cur_lines += used_q
                    if rest_q:
                        queue[idx] = ("blockquote", rest_q)
                    else:
                        idx += 1
                    pages.append(cur_page)
                    cur_page = []
                    cur_lines = 0.0
                    continue
            if cur_page:
                pages.append(cur_page)
                cur_page = []
                cur_lines = 0.0
            else:
                if tag == "p":
                    fit_txt, rest_txt, _ = split_paragraph_to_fit(raw, MAX_LINES_PER_PAGE)
                    if fit_txt and rest_txt:
                        pages.append([("p", fit_txt)])
                        queue[idx] = ("p", rest_txt)
                        continue
                if tag == "blockquote":
                    fit_q, rest_q, _ = split_blockquote_to_fit(raw, MAX_LINES_PER_PAGE)
                    if fit_q and rest_q:
                        pages.append([("blockquote", fit_q)])
                        queue[idx] = ("blockquote", rest_q)
                        continue
                pages.append([(tag, raw)])
                idx += 1
    if cur_page:
        pages.append(cur_page)
    return pages


def expand_events(events: list) -> list:
    """Split multi-word WordBoundary events (e.g., 'Chapter 1') into single-word events."""
    expanded = []
    for ev in events:
        parts = re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*", ev["text"])
        if len(parts) <= 1:
            expanded.append(ev)
        else:
            total_chars = max(1, sum(len(p) for p in parts))
            cur_off = ev["offset"]
            for idx, p in enumerate(parts):
                dur = round(ev["duration"] * (len(p) / total_chars)) if idx < len(parts) - 1 else (ev["offset"] + ev["duration"] - cur_off)
                dur = max(200_000, dur)
                expanded.append({"text": p, "offset": cur_off, "duration": dur})
                cur_off += dur
    return expanded


def align_words_to_events(words: list, events: list) -> list:
    """Align XHTML words to TTS WordBoundary events using SequenceMatcher for zero drift."""
    ev_list = expand_events(events)
    w_norms = [normalize_token(w["text"]) for w in words]
    e_norms = [normalize_token(e["text"]) for e in ev_list]

    sm = difflib.SequenceMatcher(None, w_norms, e_norms, autojunk=False)
    aligned = [None] * len(words)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                ev = ev_list[j1 + k]
                aligned[i1 + k] = {
                    "id": words[i1 + k]["id"],
                    "sid": words[i1 + k]["sid"],
                    "text": words[i1 + k]["text"],
                    "begin": ev["offset"],
                    "end": ev["offset"] + max(ev["duration"], 500_000),
                }
        elif tag in ("replace", "delete"):
            n_w = i2 - i1
            if n_w <= 0:
                continue
            if j2 > j1:
                span_start = ev_list[j1]["offset"]
                span_end = ev_list[j2 - 1]["offset"] + max(ev_list[j2 - 1]["duration"], 500_000)
            else:
                prev_end = ev_list[j1 - 1]["offset"] + ev_list[j1 - 1]["duration"] if j1 > 0 else 0
                next_start = ev_list[j1]["offset"] if j1 < len(ev_list) else prev_end + n_w * 1_500_000
                span_start = prev_end
                span_end = max(span_start + n_w * 500_000, next_start)
            step = max(500_000, (span_end - span_start) // n_w)
            for k in range(n_w):
                b = span_start + k * step
                e = b + step if k < n_w - 1 else max(b + 500_000, span_end)
                aligned[i1 + k] = {
                    "id": words[i1 + k]["id"],
                    "sid": words[i1 + k]["sid"],
                    "text": words[i1 + k]["text"],
                    "begin": b,
                    "end": e,
                }

    for i in range(len(aligned)):
        if aligned[i] is None:
            prev_end = aligned[i - 1]["end"] if i > 0 else 0
            aligned[i] = {"id": words[i]["id"], "sid": words[i]["sid"], "text": words[i]["text"], "begin": prev_end, "end": prev_end + 1_000_000}
        aligned[i]["begin"] = max(0, aligned[i]["begin"] - LEAD_TICKS)
        aligned[i]["end"] = max(aligned[i]["begin"] + 400_000, aligned[i]["end"] - LEAD_TICKS)
        if i > 0 and aligned[i]["begin"] < aligned[i - 1]["end"]:
            if aligned[i]["begin"] > aligned[i - 1]["begin"]:
                aligned[i - 1]["end"] = aligned[i]["begin"]
            else:
                aligned[i]["begin"] = aligned[i - 1]["end"]
                if aligned[i]["end"] <= aligned[i]["begin"]:
                    aligned[i]["end"] = aligned[i]["begin"] + 400_000

    # Make SMIL clipEnd[i] == clipBegin[i+1] so Apple Books plays continuously without seeking between words
    for i in range(len(aligned) - 1):
        if aligned[i + 1]["begin"] > aligned[i]["end"]:
            aligned[i]["end"] = aligned[i + 1]["begin"]

    return aligned


def ensure_m4a(ch_num: int, audio_mp3_dir: Path, audio_m4a_dir: Path) -> Path:
    audio_m4a_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = audio_mp3_dir / f"ch{ch_num:02d}.mp3"
    m4a_path = audio_m4a_dir / f"ch{ch_num:02d}.m4a"
    if m4a_path.exists() and m4a_path.stat().st_size > 1000:
        return m4a_path
    subprocess.run(
        ["afconvert", "-f", "m4af", "-d", "aac", "-c", "2", "-b", "64000", str(mp3_path), str(m4a_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return m4a_path


STYLE_CSS = f"""@charset "utf-8";
html, body {{
  margin: 0;
  padding: 0;
  width: {PAGE_W}px;
  height: {PAGE_H}px;
  overflow: hidden;
  background-color: #ffffff;
  color: #111827;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 20px;
  line-height: 1.6;
}}
.page {{
  box-sizing: border-box;
  width: {PAGE_W}px;
  height: {PAGE_H}px;
  padding: 52px 60px 56px 60px;
  position: relative;
}}
h1 {{
  font-size: 27px;
  line-height: 1.25;
  margin: 0 0 16px 0;
  text-align: center;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 10px;
}}
h2 {{
  font-size: 22px;
  margin: 14px 0 10px 0;
}}
p {{
  margin: 0 0 14px 0;
  text-align: justify;
}}
blockquote {{
  margin: 12px 24px 16px 24px;
  padding-left: 14px;
  border-left: 3px solid #9ca3af;
  font-style: italic;
}}
.illus-wrap {{
  text-align: center;
  margin: 6px 0 18px 0;
}}
.illus-wrap img {{
  max-width: 100%;
  max-height: 400px;
  width: auto;
  height: auto;
  border: none;
  padding: 0;
  background: transparent;
  box-shadow: none;
  mix-blend-mode: multiply;
}}
.footer {{
  position: absolute;
  bottom: 24px;
  left: 64px;
  right: 64px;
  text-align: center;
  font-size: 13px;
  color: #6b7280;
  font-family: -apple-system, sans-serif;
}}
.toc-list {{
  list-style: none;
  padding: 0;
  margin: 18px 0 0 0;
}}
.toc-list li {{
  margin: 0;
  padding: 9px 0;
  border-bottom: 1px dotted #d1d5db;
  font-size: 18px;
}}
.toc-list a {{
  color: #111827;
  text-decoration: none;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  width: 100%;
}}
.toc-list a:hover {{
  text-decoration: underline;
}}
.toc-pg {{
  color: #6b7280;
  font-family: -apple-system, sans-serif;
  font-size: 14px;
}}
.front-box {{
  font-size: 16px;
  line-height: 1.65;
  color: #374151;
}}
.front-box p {{
  text-align: left;
  margin-bottom: 12px;
}}
span.sent.-epub-media-overlay-active,
span.sent.sent-active {{
  background-color: #fef9c3;
  border-radius: 4px;
}}
span.word.-epub-media-overlay-active {{
  background-color: #facc15;
  color: #111827;
  border-radius: 3px;
}}
"""


def make_cover_xhtml(title: str, author: str, subtitle: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>Cover — {html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body style="margin:0; padding:0; background:#0b151e;">
  <div style="position:relative; width:{PAGE_W}px; height:{PAGE_H}px; overflow:hidden;">
    <img src="../images/cover.jpg" alt="{html.escape(title)} Cover" style="width:100%; height:100%; object-fit:cover; display:block;"/>
    <div style="position:absolute; top:38px; left:48px; right:48px; text-align:center; background:rgba(11,21,30,0.74); border:1px solid rgba(212,175,55,0.65); border-radius:8px; padding:16px 20px;">
      <div style="font-family:Georgia,serif; font-size:30px; font-weight:bold; color:#fef3c7; line-height:1.2;">{html.escape(title)}</div>
      <div style="font-family:-apple-system,sans-serif; font-size:13px; color:#fde68a; margin-top:6px; letter-spacing:0.06em; text-transform:uppercase;">{html.escape(subtitle)}</div>
    </div>
    <div style="position:absolute; bottom:32px; left:140px; right:140px; text-align:center; background:rgba(11,21,30,0.74); border:1px solid rgba(212,175,55,0.55); border-radius:6px; padding:8px 14px;">
      <div style="font-family:Georgia,serif; font-size:16px; color:#fef3c7;">By {html.escape(author)}</div>
    </div>
  </div>
</body>
</html>
"""


def make_title_xhtml(title: str, author: str, subtitle: str, publisher: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>Title Page — {html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body>
  <div class="page" style="display:flex; flex-direction:column; justify-content:space-between; text-align:center; padding-top:110px; padding-bottom:90px;">
    <div>
      <div style="font-family:-apple-system,sans-serif; font-size:13px; letter-spacing:0.18em; text-transform:uppercase; color:#6b7280; margin-bottom:20px;">Illustrated Read-Aloud Classic</div>
      <h1 style="font-size:38px; border:none; margin-bottom:14px;">{html.escape(title)}</h1>
      <div style="font-size:20px; color:#4b5563; font-style:italic; margin-bottom:44px;">{html.escape(subtitle)}</div>
      <div style="width:90px; height:2px; background:#d1d5db; margin:0 auto 44px;"></div>
      <div style="font-size:22px; font-weight:bold; color:#111827;">{html.escape(author)}</div>
      <div style="font-size:15px; color:#6b7280; margin-top:10px;">Public Domain Classic · Modernized 2026</div>
    </div>
    <div style="font-family:-apple-system,sans-serif; font-size:14px; color:#4b5563; line-height:1.8;">
      <div><strong>{html.escape(publisher)}</strong></div>
      <div>Multi-Voice Theatrical Read-Aloud · Synchronized Word-by-Word</div>
    </div>
  </div>
</body>
</html>
"""


def make_copyright_xhtml(title: str, author: str, publisher: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>Copyright &amp; Edition Notice</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body>
  <div class="page">
    <h1>Copyright &amp; Edition Information</h1>
    <div class="front-box">
      <p><strong>{html.escape(title)}</strong></p>
      <p>Based on the original public-domain work by {html.escape(author)} (sourced from Project Gutenberg).</p>
      <p><strong>2026 Edition, Modernization &amp; Audio Synchronization</strong><br/>
      Published in 2026 by {html.escape(publisher)}.</p>
      <p><strong>Edition &amp; Accessibility Specifications</strong><br/>
      • <strong>Format:</strong> EPUB 3.0 Fixed-Layout (Pre-Paginated, 768×1024)<br/>
      • <strong>Read-Aloud Engine:</strong> SMIL 3.0 Media Overlays with two-level highlighting (sentence-level context + synchronized word-by-word tracking)<br/>
      • <strong>Narration:</strong> Multi-voice theatrical neural narration (AAC 64 kbps stereo)</p>
      <p><strong>Terms of Use</strong><br/>
      This digital edition is formatted for personal reading, family read-aloud, and educational use. The underlying classic text remains in the public domain.</p>
    </div>
    <div class="footer">ii</div>
  </div>
</body>
</html>
"""


def make_colophon_xhtml(title: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>About This Edition &amp; Colophon</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body>
  <div class="page">
    <h1>About This Edition</h1>
    <div class="front-box">
      <p><strong>About {html.escape(title)}</strong><br/>
      This unabridged 2026 edition updates dated phrasing into crisp, natural everyday English while preserving every scene, dialogue, and character voice.</p>
      <p><strong>How to Use Read Aloud in Apple Books</strong><br/>
      1. Tap the center of any chapter page to reveal the Apple Books toolbar.<br/>
      2. Tap the <strong>Read Aloud / Speaker</strong> icon at the top.<br/>
      3. As the narrator and characters speak, the active sentence is softly highlighted in pale cream-yellow while each spoken word is highlighted in bright gold-yellow.</p>
      <p><strong>Colophon</strong><br/>
      Typeset in Georgia 20pt on a 768×1024 fixed-layout grid. Audio synthesized with multi-character neural voices and word-aligned via sample-accurate boundary timestamps with -80 ms visual lead compensation.</p>
    </div>
    <div class="footer">Colophon</div>
  </div>
</body>
</html>
"""


def build_nested_smil(p_id: str, ch_idx: int, p_aligned: list) -> str:
    seqs = []
    cur_sid = None
    cur_pars = []

    def flush_seq():
        if cur_sid is not None and cur_pars:
            seqs.append(
                f'      <seq id="seq_{cur_sid}" epub:textref="../text/{p_id}.xhtml#{cur_sid}">\n'
                + "\n".join(cur_pars)
                + "\n      </seq>"
            )

    for k, item in enumerate(p_aligned, 1):
        if item["sid"] != cur_sid:
            flush_seq()
            cur_sid = item["sid"]
            cur_pars = []
        cb = format_smil_time(item["begin"])
        ce = format_smil_time(item["end"])
        cur_pars.append(
            f'        <par id="par{k}">\n'
            f'          <text src="../text/{p_id}.xhtml#{item["id"]}"/>\n'
            f'          <audio src="../audio/ch{ch_idx:02d}.m4a" clipBegin="{cb}" clipEnd="{ce}"/>\n'
            f'        </par>'
        )
    flush_seq()

    return f"""<?xml version="1.0" encoding="utf-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq id="seq_page" epub:textref="../text/{p_id}.xhtml">
{chr(10).join(seqs)}
    </seq>
  </body>
</smil>
"""


HIGHLIGHT_JS = """(function () {
  var activeSent = null;
  function syncSentenceHighlight() {
    var w = document.querySelector('span.word.-epub-media-overlay-active');
    var nextSent = w ? w.closest('span.sent') : null;
    if (activeSent && activeSent !== nextSent) {
      activeSent.classList.remove('sent-active');
    }
    if (nextSent && nextSent !== activeSent) {
      nextSent.classList.add('sent-active');
    }
    activeSent = nextSent;
  }
  var obs = new MutationObserver(syncSentenceHighlight);
  window.addEventListener('DOMContentLoaded', function () {
    obs.observe(document.body, { attributes: true, attributeFilter: ['class'], subtree: true });
    syncSentenceHighlight();
  });
})();
"""


def main():
    ap = argparse.ArgumentParser(description="Build Apple Books Fixed-Layout Read-Aloud EPUB3")
    ap.add_argument("--project-dir", default=".", help="Project root containing chapters/, images/, build/")
    ap.add_argument("--title", default="Alice’s Adventures in Wonderland (2026 Modern Edition)", help="Book title")
    ap.add_argument("--author", default="Lewis Carroll", help="Book author")
    ap.add_argument("--out", default=None, help="Output .epub path (default: <project-dir>/dist/book-word-by-word.epub)")
    args = ap.parse_args()

    project_dir = Path(args.project_dir).resolve()
    chapters_dir = project_dir / "chapters"
    images_dir = project_dir / "images"
    build_dir = project_dir / "build"
    audio_mp3_dir = build_dir / "audio"
    audio_m4a_dir = build_dir / "audio_m4a"
    dist_dir = project_dir / "dist"

    dist_dir.mkdir(parents=True, exist_ok=True)
    epub_root = build_dir / "epub_fxl_src"
    if epub_root.exists():
        shutil.rmtree(epub_root)
    oebps = epub_root / "OEBPS"
    for sub in ["META-INF", "OEBPS/text", "OEBPS/smil", "OEBPS/audio", "OEBPS/styles", "OEBPS/images", "OEBPS/scripts"]:
        (epub_root / sub).mkdir(parents=True, exist_ok=True)

    (epub_root / "META-INF" / "container.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        encoding="utf-8",
    )
    (oebps / "styles" / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (oebps / "scripts" / "highlight.js").write_text(HIGHLIGHT_JS, encoding="utf-8")
    subtitle = "2026 Modern All-Ages Edition · Read Aloud"
    publisher = "2026 Modern Classics Digital Press"
    has_cover = (images_dir / "cover.jpg").exists()
    if has_cover:
        (oebps / "text" / "cover.xhtml").write_text(make_cover_xhtml(args.title, args.author, subtitle), encoding="utf-8")
    (oebps / "text" / "title.xhtml").write_text(make_title_xhtml(args.title, args.author, subtitle, publisher), encoding="utf-8")
    (oebps / "text" / "copyright.xhtml").write_text(make_copyright_xhtml(args.title, args.author, publisher), encoding="utf-8")
    (oebps / "text" / "colophon.xhtml").write_text(make_colophon_xhtml(args.title), encoding="utf-8")
    if has_cover:
        (oebps / "images" / "cover.jpg").write_bytes((images_dir / "cover.jpg").read_bytes())

    chapter_files = sorted(chapters_dir.glob("ch*.md"))
    page_counter = 0
    all_pages = []
    toc_entries = []
    total_ticks = 0

    for ch_idx, ch_path in enumerate(chapter_files, 1):
        m4a_path = ensure_m4a(ch_idx, audio_mp3_dir, audio_m4a_dir)
        (oebps / "audio" / f"ch{ch_idx:02d}.m4a").write_bytes(m4a_path.read_bytes())
        img_src = images_dir / f"ch{ch_idx:02d}.png"
        has_illus = img_src.exists()
        if has_illus:
            (oebps / "images" / f"ch{ch_idx:02d}.png").write_bytes(img_src.read_bytes())

        events = json.loads((audio_mp3_dir / f"ch{ch_idx:02d}.events.json").read_text(encoding="utf-8"))
        title, blocks = parse_markdown_blocks(ch_path.read_text(encoding="utf-8"))
        pages_blocks = paginate_blocks(title, blocks, has_illus=has_illus)

        sent_counter = [0]
        word_counter = [0]
        ch_words = []
        pages_xhtml_info = []

        for p_blocks in pages_blocks:
            page_counter += 1
            p_words_start = len(ch_words)
            body_parts = []
            for tag, raw in p_blocks:
                if tag == "h1":
                    body_parts.append(
                        f"<h1>{render_inline_sentences_and_words(raw, sent_counter, word_counter, ch_words)}</h1>"
                    )
                elif tag == "illus":
                    body_parts.append(
                        f'<div class="illus-wrap"><img src="../images/ch{ch_idx:02d}.png" alt="{html.escape(title)} Illustration"/></div>'
                    )
                elif tag == "h2":
                    body_parts.append(
                        f"<h2>{render_inline_sentences_and_words(raw, sent_counter, word_counter, ch_words)}</h2>"
                    )
                elif tag == "blockquote":
                    q_lines = [
                        render_inline_sentences_and_words(ln.strip(), sent_counter, word_counter, ch_words)
                        if ln.strip()
                        else ""
                        for ln in raw.splitlines()
                    ]
                    body_parts.append(f"<blockquote><p>{' <br/>\n'.join(q_lines)}</p></blockquote>")
                else:
                    body_parts.append(
                        f"<p>{render_inline_sentences_and_words(raw, sent_counter, word_counter, ch_words)}</p>"
                    )
            p_words_end = len(ch_words)
            pages_xhtml_info.append((page_counter, body_parts, p_words_start, p_words_end))

        aligned_ch_words = align_words_to_events(ch_words, events)

        for local_i, (p_num, body_parts, w_start, w_end) in enumerate(pages_xhtml_info):
            if local_i == 0:
                toc_entries.append((p_num, title))
            p_aligned = aligned_ch_words[w_start:w_end]
            p_id = f"p{p_num:03d}"

            xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
  <script type="text/javascript" src="../scripts/highlight.js"></script>
</head>
<body>
  <div class="page">
    {chr(10).join("    " + b for b in body_parts)}
    <div class="footer">{p_num}</div>
  </div>
</body>
</html>
"""
            (oebps / "text" / f"{p_id}.xhtml").write_text(xhtml, encoding="utf-8")
            (oebps / "smil" / f"{p_id}.smil").write_text(build_nested_smil(p_id, ch_idx, p_aligned), encoding="utf-8")

            p_dur_ticks = max(0, p_aligned[-1]["end"] - p_aligned[0]["begin"]) if p_aligned else 0
            total_ticks += p_dur_ticks
            all_pages.append({"p_id": p_id, "duration": format_smil_time(p_dur_ticks)})

        print(f"Chapter {ch_idx:02d}: {len(pages_xhtml_info)} pages, {len(aligned_ch_words)} words")

    # Machine-readable EPUB3 Navigation TOC (nav.xhtml, clean titles only for Apple Books TOC sidebar)
    nav_clean_lis = "\n".join(
        f'        <li><a href="text/p{p_num:03d}.xhtml">{html.escape(title)}</a></li>'
        for p_num, title in toc_entries
    )
    (oebps / "nav.xhtml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>Table of Contents</title>
  <link rel="stylesheet" type="text/css" href="styles/style.css"/>
</head>
<body>
  <div class="page">
    <nav epub:type="toc" id="toc">
      <h1>Table of Contents</h1>
      <ol>
        <li><a href="text/cover.xhtml">Cover</a></li>
        <li><a href="text/title.xhtml">Title Page</a></li>
        <li><a href="text/copyright.xhtml">Copyright &amp; Edition Information</a></li>
        <li><a href="text/toc.xhtml">Table of Contents</a></li>
{nav_clean_lis}
        <li><a href="text/colophon.xhtml">About This Edition &amp; Colophon</a></li>
      </ol>
    </nav>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )

    # Visual in-book Table of Contents page (text/toc.xhtml, included in spine with right-aligned page numbers)
    visual_toc_lis = "\n".join(
        f'      <li><a href="p{p_num:03d}.xhtml"><span>{html.escape(title)}</span><span class="toc-pg">{p_num}</span></a></li>'
        for p_num, title in toc_entries
    )
    (oebps / "text" / "toc.xhtml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <title>Table of Contents</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body>
  <div class="page">
    <h1>Table of Contents</h1>
    <ol class="toc-list">
      <li><a href="cover.xhtml"><span>Cover</span><span class="toc-pg">Cover</span></a></li>
      <li><a href="title.xhtml"><span>Title Page</span><span class="toc-pg">i</span></a></li>
      <li><a href="copyright.xhtml"><span>Copyright &amp; Edition Information</span><span class="toc-pg">ii</span></a></li>
{visual_toc_lis}
      <li><a href="colophon.xhtml"><span>About This Edition &amp; Colophon</span><span class="toc-pg">End</span></a></li>
    </ol>
    <div class="footer">iii</div>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )

    book_uuid = str(uuid.uuid4())

    # EPUB2 toc.ncx for universal reader compatibility
    ncx_points = [
        ('cover', 1, 'Cover', 'text/cover.xhtml'),
        ('title', 2, 'Title Page', 'text/title.xhtml'),
        ('copyright', 3, 'Copyright & Edition Information', 'text/copyright.xhtml'),
        ('nav', 4, 'Table of Contents', 'text/toc.xhtml'),
    ]
    play_order = 5
    for p_num, title in toc_entries:
        ncx_points.append((f'ch_p{p_num:03d}', play_order, title, f'text/p{p_num:03d}.xhtml'))
        play_order += 1
    ncx_points.append(('colophon', play_order, 'About This Edition & Colophon', 'text/colophon.xhtml'))

    ncx_navpoints = "\n".join(
        f"""    <navPoint id="{nid}" playOrder="{po}">
      <navLabel><text>{html.escape(label)}</text></navLabel>
      <content src="{src}"/>
    </navPoint>"""
        for nid, po, label, src in ncx_points
    )
    (oebps / "toc.ncx").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:{book_uuid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="{len(all_pages)}"/>
    <meta name="dtb:maxPageNumber" content="{len(all_pages)}"/>
  </head>
  <docTitle><text>{html.escape(args.title)}</text></docTitle>
  <navMap>
{ncx_navpoints}
  </navMap>
</ncx>
""",
        encoding="utf-8",
    )

    manifest_lines = [
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="css" href="styles/style.css" media-type="text/css"/>',
        '    <item id="js_hl" href="scripts/highlight.js" media-type="application/javascript"/>',
        *(['    <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>', '    <item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml"/>'] if has_cover else []),
        '    <item id="title" href="text/title.xhtml" media-type="application/xhtml+xml"/>',
        '    <item id="copyright" href="text/copyright.xhtml" media-type="application/xhtml+xml"/>',
        '    <item id="toc_page" href="text/toc.xhtml" media-type="application/xhtml+xml"/>',
        '    <item id="colophon" href="text/colophon.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine_lines = [
        *(['    <itemref idref="cover" properties="rendition:page-spread-center"/>'] if has_cover else []),
        '    <itemref idref="title"/>',
        '    <itemref idref="copyright"/>',
        '    <itemref idref="toc_page"/>',
    ]
    duration_metas = [f'    <meta property="media:duration">{format_smil_time(total_ticks)}</meta>']

    for ch_idx in range(1, len(chapter_files) + 1):
        manifest_lines.append(
            f'    <item id="aud_ch{ch_idx:02d}" href="audio/ch{ch_idx:02d}.m4a" media-type="audio/mp4"/>'
        )
        if (images_dir / f"ch{ch_idx:02d}.png").exists():
            manifest_lines.append(
                f'    <item id="img_ch{ch_idx:02d}" href="images/ch{ch_idx:02d}.png" media-type="image/png"/>'
            )

    for p in all_pages:
        pid = p["p_id"]
        manifest_lines.append(
            f'    <item id="{pid}" href="text/{pid}.xhtml" media-type="application/xhtml+xml" properties="scripted" media-overlay="smil_{pid}"/>'
        )
        manifest_lines.append(
            f'    <item id="smil_{pid}" href="smil/{pid}.smil" media-type="application/smil+xml"/>'
        )
        spine_lines.append(f'    <itemref idref="{pid}"/>')
        duration_metas.append(
            f'    <meta property="media:duration" refines="#smil_{pid}">{p["duration"]}</meta>'
        )

    spine_lines.append('    <itemref idref="colophon"/>')

    (oebps / "content.opf").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" prefix="rendition: http://www.idpf.org/vocab/rendition/# ibooks: http://vocabulary.itunes.apple.com/rdf/ibooks/vocabulary-extensions-1.0/ schema: http://schema.org/">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:{book_uuid}</dc:identifier>
    <dc:title>{html.escape(args.title)}</dc:title>
    <dc:creator id="creator">{html.escape(args.author)}</dc:creator>
    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
    <dc:publisher>2026 Modern Classics Digital Press</dc:publisher>
    <dc:date>2026-11-16</dc:date>
    <dc:language>en</dc:language>
    <dc:subject>Classic Fiction</dc:subject>
    <dc:subject>Fantasy</dc:subject>
    <dc:subject>Children's Literature</dc:subject>
    <dc:rights>Original 1865 text in the Public Domain; 2026 modern edition, illustrations, and synchronized audio by 2026 Modern Classics Digital Press.</dc:rights>
    <dc:description>An unabridged 2026 modernization of {html.escape(args.author)}'s classic {html.escape(args.title)}, crafted in clear, vivid English for all ages with multi-voice theatrical Read-Aloud and two-level sentence and word-by-word highlighting.</dc:description>
    {("<meta name=\"cover\" content=\"cover-image\"/>" if has_cover else "")}
    <meta property="dcterms:modified">2026-11-16T02:50:00Z</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">auto</meta>
    <meta property="ibooks:specified-fonts">true</meta>
    <meta property="schema:accessibilityFeature">synchronizedAudioText</meta>
    <meta property="schema:accessibilityFeature">tableOfContents</meta>
    <meta property="schema:accessibilityFeature">readingOrder</meta>
    <meta property="media:narrator">Aria Neural Voice</meta>
    <meta property="media:active-class">-epub-media-overlay-active</meta>
{chr(10).join(duration_metas)}
  </metadata>
  <manifest>
{chr(10).join(manifest_lines)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine_lines)}
  </spine>
</package>
""",
        encoding="utf-8",
    )

    epub_out = Path(args.out).resolve() if args.out else (dist_dir / "book-word-by-word.epub")
    with zipfile.ZipFile(epub_out, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for path in sorted(epub_root.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(epub_root).as_posix()
                zf.write(path, arcname, compress_type=zipfile.ZIP_DEFLATED)

    print(f"Created Retail-Grade Apple Books FXL EPUB3: {epub_out} ({epub_out.stat().st_size:,} bytes, {len(all_pages)} story pages + 5 front/back matter pages)")


if __name__ == "__main__":
    main()
