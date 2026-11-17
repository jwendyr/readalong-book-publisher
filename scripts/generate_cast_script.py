#!/usr/bin/env python3
"""Generate an editable cast_script.json and interactive Cast/Emotion/SFX Studio HTML
so speakers, emotions, ambiance, and SFX can be audited and edited before TTS rendering."""

import argparse
import json
import re
from pathlib import Path

EMOTION_PRESETS = {
    "neutral": {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%"},
    "cheerful": {"rate": "+6%", "pitch": "+4Hz", "volume": "+5%"},
    "sad": {"rate": "-10%", "pitch": "-4Hz", "volume": "-8%"},
    "angry": {"rate": "+8%", "pitch": "+5Hz", "volume": "+12%"},
    "spooky": {"rate": "-14%", "pitch": "-8Hz", "volume": "-10%"},
    "whisper": {"rate": "-8%", "pitch": "-2Hz", "volume": "-22%"},
    "hurried": {"rate": "+14%", "pitch": "+3Hz", "volume": "+2%"},
    "solemn": {"rate": "-8%", "pitch": "-5Hz", "volume": "+0%"},
}

VOICE_CAST = {
    "narrator": ("en-US-AriaNeural", "neutral"),
    "alice": ("en-US-AvaMultilingualNeural", "cheerful"),
    "rabbit": ("en-US-RogerNeural", "hurried"),
    "mouse": ("en-US-JennyNeural", "neutral"),
    "dodo": ("en-US-ChristopherNeural", "solemn"),
    "caterpillar": ("en-US-GuyNeural", "solemn"),
    "duchess": ("en-US-MichelleNeural", "angry"),
    "cheshire": ("en-US-AndrewMultilingualNeural", "neutral"),
    "hatter": ("en-US-BrianMultilingualNeural", "cheerful"),
    "hare": ("en-US-EricNeural", "hurried"),
    "dormouse": ("en-US-AnaNeural", "sad"),
    "queen": ("en-US-AriaNeural", "angry"),
    "king": ("en-US-ChristopherNeural", "solemn"),
    "gryphon": ("en-US-GuyNeural", "neutral"),
    "turtle": ("en-US-SteffanNeural", "sad"),
    "scrooge": ("en-US-GuyNeural", "angry"),
    "cratchit": ("en-US-BrianMultilingualNeural", "neutral"),
    "fred": ("en-US-AndrewMultilingualNeural", "cheerful"),
    "marley": ("en-US-ChristopherNeural", "spooky"),
    "spirit": ("en-US-AvaMultilingualNeural", "spooky"),
    "tim": ("en-US-AnaNeural", "cheerful"),
    "other": ("en-US-JennyNeural", "neutral"),
}

CHAR_PATTERNS = [
    ("tiny tim", "tim"), ("bob cratchit", "cratchit"), ("cratchit", "cratchit"),
    ("ebenezer scrooge", "scrooge"), ("scrooge", "scrooge"), ("marley", "marley"),
    ("fred", "fred"), ("nephew", "fred"), ("fezziwig", "gryphon"),
    ("ghost", "spirit"), ("spirit", "spirit"), ("belle", "alice"),
    ("mock turtle", "turtle"), ("turtle", "turtle"), ("march hare", "hare"),
    ("hare", "hare"), ("mad hatter", "hatter"), ("hatter", "hatter"),
    ("dormouse", "dormouse"), ("white rabbit", "rabbit"), ("rabbit", "rabbit"),
    ("cheshire", "cheshire"), ("cat", "cheshire"), ("caterpillar", "caterpillar"),
    ("duchess", "duchess"), ("queen", "queen"), ("king", "king"),
    ("gryphon", "gryphon"), ("dodo", "dodo"), ("mouse", "mouse"),
    ("alice", "alice"), ("bob", "cratchit"), ("tim", "tim"),
]


def parse_markdown_blocks(md_text: str):
    lines = md_text.strip().splitlines()
    title = "Chapter"
    blocks, para_buf, quote_buf = [], [], []
    for line in lines:
        s = line.strip()
        if s.startswith("# ") and title == "Chapter":
            title = s[2:].strip()
            continue
        if s.startswith(">"):
            if para_buf:
                blocks.append(("p", " ".join(para_buf).strip()))
                para_buf.clear()
            quote_buf.append(s[1:].strip())
        elif s == "":
            if para_buf:
                blocks.append(("p", " ".join(para_buf).strip()))
                para_buf.clear()
            if quote_buf:
                blocks.append(("blockquote", "\n".join(quote_buf).strip()))
                quote_buf.clear()
        else:
            if quote_buf:
                blocks.append(("blockquote", "\n".join(quote_buf).strip()))
                quote_buf.clear()
            para_buf.append(s)
    if para_buf:
        blocks.append(("p", " ".join(para_buf).strip()))
    if quote_buf:
        blocks.append(("blockquote", "\n".join(quote_buf).strip()))
    return title, blocks


def detect_speaker(after: str, before: str, last_char: str):
    for window in (after.lower()[:110], before.lower()[-120:]):
        for kw, role in CHAR_PATTERNS:
            if re.search(rf"\b{re.escape(kw)}\b", window):
                return role, "high"
    return (last_char if last_char != "narrator" else "other"), "low"


def suggest_ambiance(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("ghost", "chain", "phantom", "spectre", "grave", "darkness")):
        return "spooky_manor"
    if any(k in t for k in ("fire", "hearth", "candle", "warm")):
        return "cozy_fireplace"
    if any(k in t for k in ("snow", "frost", "fog", "wind", "cold")):
        return "winter_wind"
    if any(k in t for k in ("bell", "clock", "chime", "midnight")):
        return "clock_ticking"
    return "none"


STUDIO_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Read-Along Cast, Emotion &amp; SFX Studio</title>
  <style>
    :root { --bg:#0f172a; --card:#1e293b; --text:#e2e8f0; --muted:#94a3b8; --border:#334155; --accent:#38bdf8; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--text); }
    header { position:sticky; top:0; z-index:20; background:var(--card); border-bottom:1px solid var(--border); padding:0.85rem 1.25rem; display:flex; flex-wrap:wrap; gap:0.75rem; align-items:center; justify-content:space-between; }
    .controls { display:flex; flex-wrap:wrap; gap:0.5rem; align-items:center; }
    select, input, button { background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:0.4rem 0.65rem; font-size:0.85rem; }
    button.primary { background:var(--accent); color:#0f172a; font-weight:600; border-color:var(--accent); cursor:pointer; }
    main { max-width:1100px; margin:1.25rem auto; padding:0 1rem 4rem; }
    .seg { background:var(--card); border:1px solid var(--border); border-left:5px solid #64748b; border-radius:10px; padding:0.85rem 1rem; margin-bottom:0.75rem; }
    .seg.low { border-left-color:#f59e0b; }
    .seg.role-narrator { border-left-color:#94a3b8; }
    .seg.role-scrooge, .seg.role-queen { border-left-color:#ef4444; }
    .seg.role-alice, .seg.role-tim { border-left-color:#38bdf8; }
    .seg.role-marley, .seg.role-spirit { border-left-color:#a855f7; }
    .seg-top { display:flex; flex-wrap:wrap; gap:0.5rem; align-items:center; margin-bottom:0.5rem; font-size:0.82rem; color:var(--muted); }
    .seg-text { font-family:Georgia,serif; font-size:1.05rem; line-height:1.55; }
    .badge { padding:0.15rem 0.45rem; border-radius:6px; font-size:0.75rem; font-weight:600; background:#334155; color:#f8fafc; }
    .badge.low { background:#78350f; color:#fde68a; }
  </style>
</head>
<body>
  <header>
    <div><strong id="bookTitle">Cast, Emotion &amp; SFX Studio</strong> <span id="stats" style="color:var(--muted);font-size:0.85rem;margin-left:0.5rem;"></span></div>
    <div class="controls">
      <select id="chFilter"></select>
      <select id="confFilter">
        <option value="all">All Segments</option>
        <option value="low">Needs Audit (Low Confidence)</option>
        <option value="dialogue">Dialogue Only</option>
      </select>
      <button id="exportBtn" class="primary">Export cast_script.json</button>
    </div>
  </header>
  <main id="list"></main>
  <script>
    let scriptData = null;
    const ROLES = ['narrator','scrooge','cratchit','fred','marley','spirit','tim','alice','rabbit','hatter','cheshire','caterpillar','queen','king','turtle','gryphon','other'];
    const EMOTIONS = ['neutral','cheerful','sad','angry','spooky','whisper','hurried','solemn'];
    const AMBIANCES = ['none','cozy_fireplace','winter_wind','spooky_manor','clock_ticking','festive_bells'];
    const SFXS = ['none','chains_rattle','door_creak','bell_chime','footsteps','thunder','tea_clink'];

    function render() {
      const chIdx = document.getElementById('chFilter').value;
      const cf = document.getElementById('confFilter').value;
      const list = document.getElementById('list');
      list.innerHTML = '';
      const ch = scriptData.chapters[Number(chIdx)];
      ch.segments.forEach((s, i) => {
        if (cf === 'low' && s.confidence !== 'low') return;
        if (cf === 'dialogue' && s.role === 'narrator') return;
        const div = document.createElement('div');
        div.className = `seg role-${s.role} ${s.confidence === 'low' ? 'low' : ''}`;
        div.innerHTML = `
          <div class="seg-top">
            <span class="badge ${s.confidence === 'low' ? 'low' : ''}">#${i+1} · ${s.confidence === 'low' ? 'Audit?' : 'Auto'}</span>
            <label>Speaker: <select data-k="role">${ROLES.map(r=>`<option ${r===s.role?'selected':''}>${r}</option>`).join('')}</select></label>
            <label>Emotion: <select data-k="emotion">${EMOTIONS.map(e=>`<option ${e===s.emotion?'selected':''}>${e}</option>`).join('')}</select></label>
            <label>Ambiance: <select data-k="ambiance">${AMBIANCES.map(a=>`<option ${a===s.ambiance?'selected':''}>${a}</option>`).join('')}</select></label>
            <label>SFX: <select data-k="sfx">${SFXS.map(x=>`<option ${x===s.sfx?'selected':''}>${x}</option>`).join('')}</select></label>
          </div>
          <div class="seg-text">${s.text.replace(/</g,'&lt;')}</div>
        `;
        div.querySelectorAll('select').forEach(sel => {
          sel.onchange = () => { s[sel.dataset.k] = sel.value; if (sel.dataset.k === 'role') s.confidence = 'manual'; };
        });
        list.appendChild(div);
      });
    }

    document.getElementById('exportBtn').onclick = () => {
      const blob = new Blob([JSON.stringify(scriptData, null, 2)], {type:'application/json'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'cast_script.json';
      a.click();
    };

    fetch('cast_script.json').then(r => r.json()).then(d => {
      scriptData = d;
      document.getElementById('bookTitle').textContent = `${d.title} — Cast & SFX Studio`;
      const total = d.chapters.reduce((a, c) => a + c.segments.length, 0);
      const low = d.chapters.reduce((a, c) => a + c.segments.filter(s => s.confidence === 'low').length, 0);
      document.getElementById('stats').textContent = `${total} segments (${low} flagged for audit)`;
      const chFilter = document.getElementById('chFilter');
      d.chapters.forEach((c, i) => {
        const o = document.createElement('option'); o.value = i; o.textContent = c.title; chFilter.appendChild(o);
      });
      chFilter.onchange = render;
      document.getElementById('confFilter').onchange = render;
      render();
    });
  </script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Generate editable cast_script.json and Cast Studio HTML")
    ap.add_argument("--project-dir", required=True, help="Project root containing chapters/")
    ap.add_argument("--title", default="Book", help="Book title")
    args = ap.parse_args()

    proj = Path(args.project_dir).resolve()
    studio_dir = proj / "studio"
    studio_dir.mkdir(parents=True, exist_ok=True)

    chapters_out = []
    total_segs, low_conf = 0, 0

    for ch_path in sorted((proj / "chapters").glob("ch*.md")):
        title, blocks = parse_markdown_blocks(ch_path.read_text(encoding="utf-8"))
        segs = [{"role": "narrator", "voice": VOICE_CAST["narrator"][0], "emotion": "neutral", "rate": "+0%", "pitch": "+0Hz", "volume": "+0%", "ambiance": "none", "sfx": "none", "confidence": "high", "text": title}]
        last_char = "narrator"
        for tag, raw in blocks:
            clean = re.sub(r"\*+", "", raw).strip()
            if not clean:
                continue
            if tag == "blockquote":
                role = last_char if last_char != "narrator" else "narrator"
                voice, emo = VOICE_CAST.get(role, VOICE_CAST["narrator"])
                preset = EMOTION_PRESETS[emo]
                segs.append({"role": role, "voice": voice, "emotion": emo, **preset, "ambiance": suggest_ambiance(clean), "sfx": "none", "confidence": "high", "text": clean})
                continue
            parts = re.split(r'("[^"]+")', clean)
            for idx, part in enumerate(parts):
                txt = part.strip()
                if not txt or not re.search(r"[A-Za-z0-9]", txt):
                    continue
                if txt.startswith('"') and txt.endswith('"') and len(txt) > 2:
                    before = parts[idx - 1] if idx > 0 else ""
                    after = parts[idx + 1] if idx + 1 < len(parts) else ""
                    role, conf = detect_speaker(after, before, last_char)
                    last_char = role
                    voice, emo = VOICE_CAST.get(role, VOICE_CAST["other"])
                    preset = EMOTION_PRESETS[emo]
                    segs.append({"role": role, "voice": voice, "emotion": emo, **preset, "ambiance": suggest_ambiance(txt), "sfx": "none", "confidence": conf, "text": txt})
                else:
                    segs.append({"role": "narrator", "voice": VOICE_CAST["narrator"][0], "emotion": "neutral", **EMOTION_PRESETS["neutral"], "ambiance": suggest_ambiance(txt), "sfx": "none", "confidence": "high", "text": txt})
        total_segs += len(segs)
        low_conf += sum(1 for s in segs if s["confidence"] == "low")
        chapters_out.append({"chapter": ch_path.stem, "title": title, "segments": segs})

    (studio_dir / "cast_script.json").write_text(json.dumps({"title": args.title, "chapters": chapters_out}, indent=2), encoding="utf-8")
    (studio_dir / "index.html").write_text(STUDIO_HTML, encoding="utf-8")
    print(f"Generated Cast Studio: {studio_dir / 'index.html'} ({total_segs} segments, {low_conf} flagged for audit)")


if __name__ == "__main__":
    main()
