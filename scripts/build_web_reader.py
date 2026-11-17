#!/usr/bin/env python3
"""Build an Interactive Book Reader + Live Cast/Emotion/SFX Attribute Editor (docs/index.html)."""

import argparse
import difflib
import html
import json
import re
from pathlib import Path

WEB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Read-Along Book Reader &amp; Live Cast Studio</title>
  <style>
    :root {
      --bg:#f8fafc; --panel:#ffffff; --text:#111827; --muted:#64748b; --border:#e2e8f0;
      --accent:#0284c7; --sent-hl:#fef9c3; --word-hl:#facc15; --word-txt:#111827;
    }
    body.sepia {
      --bg:#f4ecd8; --panel:#faf5e8; --text:#2b2118; --muted:#786552; --border:#dfd3bc;
      --sent-hl:#fde68a; --word-hl:#f59e0b; --word-txt:#111827;
    }
    body.dark {
      --bg:#0f172a; --panel:#1e293b; --text:#e2e8f0; --muted:#94a3b8; --border:#334155;
      --sent-hl:rgba(253,224,71,0.16); --word-hl:#facc15; --word-txt:#0f172a;
    }
    * { box-sizing:border-box; }
    body { margin:0; font-family:system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--text); }
    header {
      position:sticky; top:0; z-index:30; background:var(--panel); border-bottom:1px solid var(--border);
      padding:0.7rem 1.2rem; display:flex; flex-wrap:wrap; gap:0.6rem; align-items:center; justify-content:space-between;
    }
    .controls { display:flex; flex-wrap:wrap; gap:0.45rem; align-items:center; }
    select, input, button {
      background:var(--bg); color:var(--text); border:1px solid var(--border);
      border-radius:8px; padding:0.4rem 0.7rem; font-size:0.86rem; cursor:pointer;
    }
    button.primary { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
    .layout { max-width:1280px; margin:1.25rem auto; padding:0 1.25rem 4rem; }
    .book-col { max-width:820px; margin:0 auto; transition:margin-right 0.15s; }
    body.inspector-open .book-col { margin-left:0; margin-right:370px; max-width:840px; }
    .book-page {
      background:var(--panel); border:1px solid var(--border); border-radius:14px;
      padding:2.5rem 2.75rem; font-family:Georgia,serif; font-size:1.2rem; line-height:1.75;
      box-shadow:0 4px 20px rgba(0,0,0,0.05);
    }
    .book-page h1 { font-family:system-ui,sans-serif; text-align:center; margin-top:0; font-size:1.65rem; border-bottom:1px solid var(--border); padding-bottom:0.75rem; }
    .book-page p { margin:0 0 1rem; text-align:justify; }
    .book-page blockquote { border-left:3px solid var(--accent); margin:1rem 1.5rem; padding-left:1rem; font-style:italic; }
    .seg-span { border-radius:4px; transition:background 0.1s; cursor:pointer; }
    .seg-span.active-seg { background:var(--sent-hl); }
    .w { border-radius:3px; }
    .w.active-word { background:var(--word-hl); color:var(--word-txt); padding:0 2px; }
    .inspector {
      width:345px; position:fixed; top:4.5rem; right:1.25rem; z-index:25;
      max-height:calc(100vh - 5.5rem); overflow-y:auto;
      background:var(--panel); border:1px solid var(--border);
      border-radius:14px; padding:1.1rem; font-size:0.86rem; display:none;
      box-shadow:0 12px 32px rgba(0,0,0,0.16);
    }
    .inspector.open { display:block; }
    .inspector h3 { margin:0 0 0.65rem; font-size:0.98rem; display:flex; justify-content:space-between; align-items:center; }
    .field { margin-bottom:0.6rem; }
    .field label { display:flex; justify-content:space-between; font-size:0.74rem; color:var(--muted); margin-bottom:0.2rem; font-weight:600; text-transform:uppercase; }
    .field select, .field input[type="range"] { width:100%; }
    .field input[type="range"] { padding:0; accent-color:var(--accent); cursor:pointer; }
    .seg-preview { background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:0.55rem; font-family:Georgia,serif; font-size:0.9rem; margin-bottom:0.7rem; max-height:95px; overflow:auto; }
    .row2 { display:grid; grid-template-columns:1fr 1fr; gap:0.5rem; }
    @media (max-width:960px) {
      body.inspector-open .book-col { margin:0 auto; }
      .inspector { width:calc(100% - 2rem); left:1rem; right:1rem; top:auto; bottom:0.75rem; max-height:52vh; }
    }
  </style>
</head>
<body class="inspector-open">
  <header>
    <div><strong id="bookTitle">Read-Along Book Reader</strong></div>
    <div class="controls">
      <select id="chapterSelect"></select>
      <button id="playBtn" class="primary">Play</button>
      <select id="themeSelect">
        <option value="light">Light Paper</option>
        <option value="sepia">Sepia Paper</option>
        <option value="dark">Dark Mode</option>
      </select>
      <button id="toggleEditBtn">Edit Cast &amp; FX</button>
    </div>
  </header>
  <div class="layout">
    <div class="book-col">
      <article id="reader" class="book-page"></article>
    </div>
  </div>
  <aside id="inspector" class="inspector open">
    <h3><span>Floating Cast &amp; FX</span><span id="segBadge" style="font-size:0.76rem;color:var(--muted);">#1</span></h3>
    <div id="segTextPreview" class="seg-preview">Click any sentence to select and edit without auto-playing.</div>
    <div class="row2">
      <div class="field">
        <label>Speaker / Role</label>
        <select id="fRole">
          <option>narrator</option><option>scrooge</option><option>cratchit</option><option>fred</option>
          <option>marley</option><option>spirit</option><option>tim</option><option>alice</option>
          <option>rabbit</option><option>hatter</option><option>cheshire</option><option>caterpillar</option>
          <option>queen</option><option>king</option><option>turtle</option><option>gryphon</option><option>other</option>
        </select>
      </div>
      <div class="field">
        <label>Emotion Preset</label>
        <select id="fEmotion">
          <option>neutral</option><option>cheerful</option><option>sad</option><option>angry</option>
          <option>spooky</option><option>whisper</option><option>hurried</option><option>solemn</option>
        </select>
      </div>
    </div>
    <div class="field">
      <label>Neural Voice</label>
      <select id="fVoice">
        <option>en-US-AriaNeural</option><option>en-US-AvaMultilingualNeural</option><option>en-US-AndrewMultilingualNeural</option>
        <option>en-US-BrianMultilingualNeural</option><option>en-US-GuyNeural</option><option>en-US-ChristopherNeural</option>
        <option>en-US-JennyNeural</option><option>en-US-RogerNeural</option><option>en-US-AnaNeural</option><option>en-US-EricNeural</option>
        <option>en-GB-SoniaNeural</option><option>en-GB-MaisieNeural</option><option>en-GB-ThomasNeural</option>
        <option>en-GB-RyanNeural</option><option>en-GB-LibbyNeural</option><option>en-AU-NatashaNeural</option><option>en-AU-WilliamMultilingualNeural</option>
      </select>
    </div>
    <div class="field">
      <label><span>Rate</span><span id="fRateVal">+0%</span></label>
      <input id="fRate" type="range" min="-50" max="100" step="2" value="0"/>
    </div>
    <div class="field">
      <label><span>Pitch</span><span id="fPitchVal">+0Hz</span></label>
      <input id="fPitch" type="range" min="-50" max="50" step="1" value="0"/>
    </div>
    <div class="field">
      <label><span>Volume</span><span id="fVolumeVal">+0%</span></label>
      <input id="fVolume" type="range" min="-50" max="50" step="2" value="0"/>
    </div>
    <div class="row2">
      <div class="field">
        <label>Ambiance</label>
        <select id="fAmbiance">
          <option>none</option><option>cozy_fireplace</option><option>winter_wind</option>
          <option>spooky_manor</option><option>clock_ticking</option><option>festive_bells</option>
        </select>
      </div>
      <div class="field">
        <label>Spot SFX</label>
        <select id="fSfx">
          <option>none</option><option>chains_rattle</option><option>knocker</option>
          <option>bell_chime</option><option>door_creak</option><option>footsteps</option><option>thunder</option>
        </select>
      </div>
    </div>
    <div style="display:flex;gap:0.5rem;margin-top:0.65rem;">
      <button id="auditionBtn" style="flex:1;">&#9654; Play Segment</button>
      <button id="exportBtn" class="primary" style="flex:1;">Export JSON</button>
    </div>
  </aside>
  <audio id="audioEl"></audio>

  <script>
    const EMO_PRESETS = {
      neutral:{rate:'+0%',pitch:'+0Hz',volume:'+0%'},
      cheerful:{rate:'+6%',pitch:'+4Hz',volume:'+5%'},
      sad:{rate:'-10%',pitch:'-4Hz',volume:'-8%'},
      angry:{rate:'+8%',pitch:'+5Hz',volume:'+12%'},
      spooky:{rate:'-14%',pitch:'-8Hz',volume:'-10%'},
      whisper:{rate:'-8%',pitch:'-2Hz',volume:'-22%'},
      hurried:{rate:'+14%',pitch:'+3Hz',volume:'+2%'},
      solemn:{rate:'-8%',pitch:'-5Hz',volume:'+0%'}
    };
    let bookData = null, curCh = 0, words = [], segs = [], activeWord = -1, activeSeg = -1, stopAtSec = null;
    const audioEl = document.getElementById('audioEl');
    const playBtn = document.getElementById('playBtn');
    const reader = document.getElementById('reader');
    const inspector = document.getElementById('inspector');

    const parseNum = (v) => parseInt(String(v || '0').replace(/[^0-9-]/g, ''), 10) || 0;
    const fmtPct = (n) => (n >= 0 ? `+${n}%` : `${n}%`);
    const fmtHz = (n) => (n >= 0 ? `+${n}Hz` : `${n}Hz`);

    function populateInspector(si) {
      const s = segs[si];
      if (!s) return;
      document.getElementById('segBadge').textContent = `#${si+1} (${s.confidence || 'auto'})`;
      document.getElementById('segTextPreview').textContent = s.text;
      document.getElementById('fRole').value = s.role;
      document.getElementById('fEmotion').value = s.emotion;
      document.getElementById('fVoice').value = s.voice;
      const r = parseNum(s.rate), p = parseNum(s.pitch), v = parseNum(s.volume);
      document.getElementById('fRate').value = r; document.getElementById('fRateVal').textContent = fmtPct(r);
      document.getElementById('fPitch').value = p; document.getElementById('fPitchVal').textContent = fmtHz(p);
      document.getElementById('fVolume').value = v; document.getElementById('fVolumeVal').textContent = fmtPct(v);
      document.getElementById('fAmbiance').value = s.ambiance;
      document.getElementById('fSfx').value = s.sfx;
    }

    function setActive(wi, si, scroll = true) {
      if (activeWord >= 0 && words[activeWord]) words[activeWord].el.classList.remove('active-word');
      if (activeSeg >= 0 && segs[activeSeg]?.el) segs[activeSeg].el.classList.remove('active-seg');
      activeWord = wi; activeSeg = si;
      if (si >= 0 && segs[si]?.el) {
        segs[si].el.classList.add('active-seg');
        populateInspector(si);
      }
      if (wi >= 0 && words[wi]) {
        words[wi].el.classList.add('active-word');
        if (scroll) words[wi].el.scrollIntoView({block:'center', behavior:'smooth'});
      }
    }

    function loadChapter(idx) {
      audioEl.pause(); stopAtSec = null; playBtn.textContent = 'Play';
      curCh = idx;
      const ch = bookData.chapters[idx];
      reader.innerHTML = ch.html;
      audioEl.src = ch.audio;
      segs = ch.segments.map((s, i) => ({...s, el: document.getElementById(`seg_${i}`)}));
      words = ch.words.map(w => ({...w, el: document.getElementById(w.id)})).filter(w => w.el);

      // Clicking a word or sentence selects it for editing & seeks without forcing auto-play
      words.forEach((w, i) => {
        w.el.classList.add('w');
        w.el.onclick = (e) => {
          e.stopPropagation();
          stopAtSec = null;
          setActive(i, w.segIdx, false);
          audioEl.currentTime = w.beginSec;
        };
      });
      segs.forEach((s, si) => {
        if (!s.el) return;
        s.el.onclick = () => {
          stopAtSec = null;
          setActive(-1, si, false);
          audioEl.currentTime = s.beginSec;
        };
      });
      setActive(0, 0, false);
    }

    audioEl.addEventListener('timeupdate', () => {
      const t = audioEl.currentTime;
      if (stopAtSec !== null && t >= stopAtSec) {
        audioEl.pause(); stopAtSec = null; playBtn.textContent = 'Play';
        return;
      }
      let lo = 0, hi = words.length - 1, fw = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (words[mid].beginSec <= t) { fw = mid; lo = mid + 1; } else { hi = mid - 1; }
      }
      if (fw >= 0 && fw !== activeWord) setActive(fw, words[fw].segIdx, true);
    });

    playBtn.onclick = () => {
      stopAtSec = null;
      if (audioEl.paused) { audioEl.play(); playBtn.textContent = 'Pause'; }
      else { audioEl.pause(); playBtn.textContent = 'Play'; }
    };
    document.getElementById('auditionBtn').onclick = () => {
      if (activeSeg < 0 || !segs[activeSeg]) return;
      const s = segs[activeSeg];
      audioEl.currentTime = s.beginSec;
      stopAtSec = s.endSec;
      audioEl.play();
      playBtn.textContent = 'Pause';
    };
    document.getElementById('toggleEditBtn').onclick = () => {
      const open = inspector.classList.toggle('open');
      document.body.classList.toggle('inspector-open', open);
    };
    document.getElementById('themeSelect').onchange = (e) => {
      const th = e.target.value === 'light' ? '' : e.target.value;
      document.body.className = (inspector.classList.contains('open') ? 'inspector-open ' : '') + th;
    };
    document.getElementById('chapterSelect').onchange = (e) => loadChapter(Number(e.target.value));

    ['fRole','fVoice','fAmbiance','fSfx'].forEach(id => {
      document.getElementById(id).onchange = (e) => {
        if (activeSeg < 0 || !segs[activeSeg]) return;
        const key = id.replace('f','').toLowerCase();
        segs[activeSeg][key] = e.target.value;
        segs[activeSeg].confidence = 'manual';
        bookData.chapters[curCh].segments[activeSeg][key] = e.target.value;
      };
    });
    document.getElementById('fRate').oninput = (e) => {
      const val = fmtPct(Number(e.target.value));
      document.getElementById('fRateVal').textContent = val;
      if (activeSeg >= 0 && segs[activeSeg]) { segs[activeSeg].rate = val; bookData.chapters[curCh].segments[activeSeg].rate = val; }
    };
    document.getElementById('fPitch').oninput = (e) => {
      const val = fmtHz(Number(e.target.value));
      document.getElementById('fPitchVal').textContent = val;
      if (activeSeg >= 0 && segs[activeSeg]) { segs[activeSeg].pitch = val; bookData.chapters[curCh].segments[activeSeg].pitch = val; }
    };
    document.getElementById('fVolume').oninput = (e) => {
      const val = fmtPct(Number(e.target.value));
      document.getElementById('fVolumeVal').textContent = val;
      if (activeSeg >= 0 && segs[activeSeg]) { segs[activeSeg].volume = val; bookData.chapters[curCh].segments[activeSeg].volume = val; }
    };
    document.getElementById('fEmotion').onchange = (e) => {
      if (activeSeg < 0 || !segs[activeSeg]) return;
      const emo = e.target.value, p = EMO_PRESETS[emo];
      segs[activeSeg].emotion = emo;
      segs[activeSeg].rate = p.rate; segs[activeSeg].pitch = p.pitch; segs[activeSeg].volume = p.volume;
      Object.assign(bookData.chapters[curCh].segments[activeSeg], {emotion:emo, ...p});
      populateInspector(activeSeg);
    };

    document.getElementById('exportBtn').onclick = () => {
      const out = {
        title: bookData.title,
        chapters: bookData.chapters.map(c => ({
          chapter: c.chapter, title: c.title,
          segments: c.segments.map(({el, beginSec, endSec, ...rest}) => rest)
        }))
      };
      const blob = new Blob([JSON.stringify(out, null, 2)], {type:'application/json'});
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'cast_script.json'; a.click();
    };

    fetch('data/book.json').then(r => r.json()).then(d => {
      bookData = d;
      document.getElementById('bookTitle').textContent = d.title;
      const sel = document.getElementById('chapterSelect');
      d.chapters.forEach((c, i) => {
        const o = document.createElement('option'); o.value = i; o.textContent = c.title; sel.appendChild(o);
      });
      loadChapter(0);
    });
  </script>
</body>
</html>
"""


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def align_words(words: list, events: list) -> list:
    ev_list = []
    for ev in events:
        parts = re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*", ev["text"])
        if len(parts) <= 1:
            ev_list.append(ev)
        else:
            tc = max(1, sum(len(p) for p in parts))
            cur = ev["offset"]
            for idx, p in enumerate(parts):
                dur = round(ev["duration"] * (len(p) / tc)) if idx < len(parts) - 1 else (ev["offset"] + ev["duration"] - cur)
                ev_list.append({"text": p, "offset": cur, "duration": max(200_000, dur)})
                cur += max(200_000, dur)

    w_norms = [norm(w["text"]) for w in words]
    e_norms = [norm(e["text"]) for e in ev_list]
    sm = difflib.SequenceMatcher(None, w_norms, e_norms, autojunk=False)
    out = [0.0] * len(words)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = max(0.0, round((ev_list[j1 + k]["offset"] - 800_000) / 1e7, 3))
        elif tag in ("replace", "delete"):
            n_w = i2 - i1
            if n_w <= 0:
                continue
            s0 = ev_list[j1]["offset"] if j1 < len(ev_list) else (ev_list[-1]["offset"] if ev_list else 0)
            s1 = (ev_list[j2 - 1]["offset"] + ev_list[j2 - 1]["duration"]) if j2 > j1 else s0 + n_w * 1_500_000
            step = max(400_000, (s1 - s0) // n_w)
            for k in range(n_w):
                out[i1 + k] = max(0.0, round((s0 + k * step - 800_000) / 1e7, 3))
    return out


def main():
    ap = argparse.ArgumentParser(description="Build Interactive Book Reader + Live Cast Inspector")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--title", required=True)
    args = ap.parse_args()

    proj = Path(args.project_dir).resolve()
    docs = proj / "docs"
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(WEB_HTML, encoding="utf-8")

    chapters_out = []
    for ch_idx, meta_path in enumerate(sorted((proj / "build" / "audio").glob("ch*.segments_meta.json")), 1):
        segs = json.loads(meta_path.read_text(encoding="utf-8"))
        events = json.loads((proj / "build" / "audio" / f"ch{ch_idx:02d}.events.json").read_text(encoding="utf-8"))
        ch_title = segs[0]["text"] if segs else f"Chapter {ch_idx}"

        words = []
        w_idx = 0
        html_parts = []
        for si, s in enumerate(segs):
            tokens = re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|[^\w\s]+|\s+", s["text"])
            seg_toks = []
            for tok in tokens:
                if re.match(r"^[A-Za-z0-9]", tok):
                    w_idx += 1
                    wid = f"w{w_idx:05d}"
                    words.append({"id": wid, "segIdx": si, "text": tok})
                    seg_toks.append(f'<span id="{wid}">{html.escape(tok)}</span>')
                else:
                    seg_toks.append(html.escape(tok))
            inner = "".join(seg_toks)
            if si == 0:
                html_parts.append(f'<h1><span class="seg-span" id="seg_{si}">{inner}</span></h1>')
            else:
                html_parts.append(f'<span class="seg-span" id="seg_{si}">{inner}</span> ')

        # Group non-heading segments cleanly into readable paragraphs
        body_html = html_parts[0] + "<p>" + "</p><p>".join(
            "".join(html_parts[i:i+3]) for i in range(1, len(html_parts), 3)
        ) + "</p>"

        begins = align_words(words, events)
        for w, bsec in zip(words, begins):
            w["beginSec"] = bsec

        chapters_out.append({
            "chapter": f"ch{ch_idx:02d}",
            "title": ch_title,
            "audio": f"audio/ch{ch_idx:02d}.m4a",
            "html": body_html,
            "segments": segs,
            "words": words,
        })

    (docs / "data" / "book.json").write_text(json.dumps({"title": args.title, "chapters": chapters_out}), encoding="utf-8")
    print(f"Built Interactive Book Reader + Live Studio: {docs / 'index.html'}")


if __name__ == "__main__":
    main()
