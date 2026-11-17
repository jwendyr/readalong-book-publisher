---
name: readalong-book-publisher
description: >
  End-to-end pipeline to adapt, translate, or modernize a book (e.g. public domain classics)
  into a retail-grade, illustrated Apple Books Read-Aloud Fixed-Layout EPUB3 with multi-voice
  theatrical narration, two-level (sentence + word) synchronized highlighting, interactive web
  reader, W3C EPUBCheck validation, and GitHub publishing. Use when asked to create a
  read-along book, word-by-word EPUB3, or modernize/translate and publish a book.
---

# Read-Along Book Publisher (Adaptation → Apple Books EPUB3 → GitHub)

Complete, battle-tested workflow for turning any source book into a retail-grade **Apple Books Fixed-Layout Read-Aloud EPUB3** + **Interactive Web Reader** and publishing it to GitHub.

## Prerequisites (macOS)
- `python3`, `uv`, `afconvert` (built-in macOS), `java` (for W3C EPUBCheck 5.1.0), `git`, `gh` (authenticated).
- Bundled scripts in this skill's `scripts/` directory:
  - `scripts/clean_illustrations.py` — strips paper-cut edges and converts illustrations to transparent RGBA PNGs.
  - `scripts/synthesize_multivoice.py` — multi-character `edge-tts` synthesis with 24kHz PCM WAV stitching and sample-accurate `WordBoundary` offsets.
  - `scripts/build_readalong_epub.py` — builds the retail-grade Fixed-Layout EPUB3 with front/back matter, two-level highlighting, and gapless SMIL.

---

## Phase 1: Source Acquisition & Chapter Splitting

1. If no local file is provided, locate the public-domain text (e.g., Project Gutenberg plain UTF-8 `.txt`).
2. Save the raw source under `<project>/original/` and split cleanly into `chapters/ch01.md` .. `chapters/chNN.md`.

---

## Phase 2: Translation / Modernization (Parallel Subagents)

1. Launch parallel `self` subagents (2 chapters per subagent, `Model: "flash"`) to translate/modernize 100% of every chapter into the target language/style (e.g., clear modern 2026 English for all ages).
2. **Strict formatting rules**:
   - Never summarize, abridge, or skip paragraphs, dialogue, or poems.
   - Format headings as `# Chapter N: <Title>`, quotes/poems as `>` blockquotes, and dialogue in standard `"..."` quotes.
   - **Avoid 2–3 word chopped poem lines** (e.g., concrete/shaped poems): format them as full rhythmic verse lines so TTS narration and page layout flow naturally.
3. Combine all chapters into `<project>/BOOK.md` and write `<project>/README.md` + `.gitignore` (ignoring `build/`, `.venv/`, `.DS_Store`).

---

## Phase 3: Cover & Frameless Illustrations

1. Use `image-generator` subagents to create:
   - **1 Cover** (`images/cover.jpg`, 3:4 portrait, **no text** — crisp title/author typography is overlaid in `cover.xhtml`).
   - **1 Illustration per chapter** (`images/ch01`..`chNN`, 4:3 open vignette on pure white `#FFFFFF`, no border/frame).
2. **Mandatory post-processing & visual check**:
   - Run `clean_illustrations.py` to erase outer paper-cut shadows/smudges and convert white backgrounds to **true transparent RGBA PNGs** (`alpha=0` outside ink) so illustrations blend seamlessly on White, Sepia, and Dark themes.
   - Generate a contact sheet on a cream background and inspect it with `read_file` to verify **zero paper-cut edges or rectangular frames** remain.

---

## Phase 4: Cast Audit Studio & Multi-Voice Theatrical Narration

1. **Pre-Render Audit (`generate_cast_script.py`)**:
   - Generate `studio/cast_script.json` and `studio/index.html` before rendering audio.
   - Review/filter segments flagged as `low` confidence in the browser UI, manually adjust **Speaker**, **Emotion** (`neutral`, `cheerful`, `sad`, `angry`, `spooky`, `whisper`, `hurried`, `solemn`), **Background Ambiance** (`cozy_fireplace`, `winter_wind`, `spooky_manor`, `clock_ticking`, `festive_bells`), and **SFX** (`chains_rattle`, `door_creak`, `bell_chime`, `footsteps`, `thunder`, `tea_clink`), then export `cast_script.json`.
2. **Multi-Voice Synthesis (`synthesize_multivoice.py`)**:

1. Assign distinct neural voices to the **Narrator** (e.g., `en-GB-SoniaNeural`) and each major character (`en-GB-MaisieNeural`, `en-US-RogerNeural`, `en-GB-RyanNeural`, `en-GB-ThomasNeural`, `en-US-AndrewMultilingualNeural`, `en-US-AriaNeural`, `en-US-ChristopherNeural`, `en-US-GuyNeural`, `en-US-AnaNeural`, etc.).
2. **Critical pitfalls avoided by `synthesize_multivoice.py`**:
   - **Skip punctuation-only segments** (`not re.search(r"[A-Za-z0-9]", txt)`) before calling `edge-tts`, otherwise `edge-tts` raises `NoAudioReceived`.
   - **Sample-accurate concatenation**: Convert each segment MP3 to `24 kHz` 16-bit mono PCM WAV via `afconvert`, insert `80 ms` silence between speaker turns, shift each segment's `WordBoundary` offsets by exact cumulative PCM frame count, then encode the full chapter WAV to stereo AAC `.m4a` (`64 kbps`) via `afconvert`.

---

## Phase 5: Retail-Grade Apple Books Fixed-Layout EPUB3 (`build_readalong_epub.py`)

Apple Books **only enables Read Aloud (speaker icon + word-by-word highlighting) on Fixed-Layout (`pre-paginated`) EPUB3s**. Enforce all of these rules:

1. **OPF (`OEBPS/content.opf`)**:
   - Exact namespace: `xmlns="http://www.idpf.org/2007/opf"` (never omit `2007/`).
   - Audio MIME type: **`media-type="audio/mp4"`** (W3C EPUBCheck rejects `audio/m4a` with `MED-005`).
   - Metadata: `rendition:layout` = `pre-paginated`, `media:active-class` = `-epub-media-overlay-active`, `media:duration` (total + refined per `#smil_pXXX`), `cover-image` property, `schema:accessibilityFeature`, `dc:publisher`, `dc:rights`, `dc:description`.
2. **Typography & Full-Page Fill (`768×1024`)**:
   - `20px` Georgia, `line-height: 1.6`, `padding: 52px 60px 56px 60px` (`CHARS_PER_LINE = 68`, `MAX_LINES_PER_PAGE = 28.0`).
   - Split long paragraphs at sentence boundaries (`split_paragraph_to_fit`) and long poems at line boundaries (`split_blockquote_to_fit`) so every page fills evenly with zero overflow.
   - Join `<br/>` lines with a trailing space (`' <br/>\n'`) so copied text never glues words together.
   - Do **not** use `hyphens: auto`.
3. **Separate Machine TOC vs. Visual TOC**:
   - `OEBPS/nav.xhtml` (`properties="nav"`, **not** in `<spine>`): clean titles only (`<li><a href="text/p001.xhtml">Chapter 1: ...</a></li>`) so Apple Books' TOC sidebar never glues page numbers onto titles.
   - `OEBPS/text/toc.xhtml` (in `<spine>`): visual Table of Contents with right-aligned page numbers (`<span>Title</span><span class="toc-pg">1</span>`).
   - Include `cover.xhtml`, `title.xhtml`, `copyright.xhtml`, `toc.xhtml`, `colophon.xhtml`, and `toc.ncx` (`toc="ncx"`).
4. **Zero-Drift, Gapless, Two-Level Highlighting**:
   - Expand multi-word TTS events (`"Chapter 1"`) and align via `difflib.SequenceMatcher` (zero cumulative drift) with `-80 ms` visual lead (`LEAD_TICKS = 800_000`).
   - Make SMIL clips gapless (`clipEnd[i] = clipBegin[i+1]`) so Apple Books plays continuously without seeking/stuttering between words.
   - Include `OEBPS/scripts/highlight.js` (`MutationObserver` + `properties="scripted"` on story pages) to highlight the parent `span.sent` (`#fef9c3`) alongside the active `span.word` (`#facc15`), since EPUBCheck rejects CSS4 `:has()` (`CSS-008`) and Apple Books ignores `<seq epub:textref>`.

---

## Phase 6: Validation & GitHub Publishing

1. Validate with **W3C EPUBCheck 5.1.0**:
   ```bash
   java -jar epubcheck.jar dist/<book>.epub
   ```
   Must report **`0 fatals / 0 errors / 0 warnings`**.
2. Create/push the repository via `git` and `gh repo create <repo> --public --source=. --remote=origin --push`.
3. Remind the user to delete any cached older copy from Apple Books Library before re-importing an updated `.epub`.
