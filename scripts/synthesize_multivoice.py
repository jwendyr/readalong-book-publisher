#!/usr/bin/env python3
"""Synthesize multi-voice theatrical narration from studio/cast_script.json
with emotion attributes (rate/pitch/volume), ducked background ambiance, spot SFX,
and sample-accurate WordBoundary timestamps."""

import argparse
import asyncio
import json
import re
import struct
import subprocess
import wave
from pathlib import Path

import edge_tts

SAMPLE_RATE = 24000
GAP_FRAMES = int(SAMPLE_RATE * 0.08)
GAP_BYTES = b"\x00\x00" * GAP_FRAMES


def read_wav_samples(path: Path) -> list:
    if not path.exists():
        return []
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return list(struct.unpack("<" + "h" * (len(raw) // 2), raw))


def mix_fx(speech: list, amb_samples: list, sfx_samples: list) -> bytes:
    n = len(speech)
    fade = min(int(SAMPLE_RATE * 0.12), max(1, n // 4))
    out = list(speech)

    if amb_samples:
        m = len(amb_samples)
        for i in range(n):
            env = 1.0
            if i < fade:
                env = i / fade
            elif i > n - fade:
                env = (n - i) / fade
            out[i] += int(amb_samples[i % m] * 0.11 * env)

    if sfx_samples:
        for i in range(min(n, len(sfx_samples))):
            out[i] += int(sfx_samples[i] * 0.38)

    clamped = [max(-32767, min(32767, s)) for s in out]
    return struct.pack("<" + "h" * n, *clamped)


async def synth_segment(sem: asyncio.Semaphore, seg_dir: Path, seg_idx: int, seg: dict):
    seg_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = seg_dir / f"seg_{seg_idx:04d}.mp3"
    wav_path = seg_dir / f"seg_{seg_idx:04d}.wav"
    ev_path = seg_dir / f"seg_{seg_idx:04d}.json"

    if wav_path.exists() and ev_path.exists() and wav_path.stat().st_size > 100:
        return wav_path, json.loads(ev_path.read_text(encoding="utf-8"))

    voice = seg.get("voice", "en-GB-SoniaNeural")
    rate = seg.get("rate", "+0%")
    pitch = seg.get("pitch", "+0Hz")
    volume = seg.get("volume", "+0%")
    text = seg["text"]

    async with sem:
        for attempt in range(4):
            try:
                comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume, boundary="WordBoundary")
                events = []

                async def _run():
                    with open(mp3_path, "wb") as f:
                        async for chunk in comm.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                            elif chunk["type"] == "WordBoundary":
                                events.append({
                                    "text": chunk["text"],
                                    "offset": chunk["offset"],
                                    "duration": chunk["duration"],
                                })

                await asyncio.wait_for(_run(), timeout=45.0)
                if mp3_path.exists() and mp3_path.stat().st_size > 0:
                    break
            except Exception as exc:
                if attempt == 3:
                    raise exc
                await asyncio.sleep(1.5 * (attempt + 1))

    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", str(mp3_path), str(wav_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ev_path.write_text(json.dumps(events), encoding="utf-8")
    return wav_path, events


async def process_chapter(ch_idx: int, ch_data: dict, project_dir: Path, fx_cache: dict):
    build_dir = project_dir / "build"
    seg_dir = build_dir / "mv_segments" / f"ch{ch_idx:02d}"
    audio_dir = build_dir / "audio"
    audio_m4a_dir = build_dir / "audio_m4a"
    docs_audio_dir = project_dir / "docs" / "audio"

    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_m4a_dir.mkdir(parents=True, exist_ok=True)
    docs_audio_dir.mkdir(parents=True, exist_ok=True)

    segs = ch_data["segments"]
    sem = asyncio.Semaphore(4)
    tasks = [synth_segment(sem, seg_dir, i, s) for i, s in enumerate(segs)]
    results = await asyncio.gather(*tasks)

    full_wav = build_dir / f"ch{ch_idx:02d}_mv.wav"
    all_events = []
    seg_metas = []
    cum_frames = 0

    with wave.open(str(full_wav), "wb") as out_w:
        out_w.setnchannels(1)
        out_w.setsampwidth(2)
        out_w.setframerate(SAMPLE_RATE)

        for idx, ((wav_path, evs), seg) in enumerate(zip(results, segs)):
            cum_ticks = round(cum_frames * 10_000_000 / SAMPLE_RATE)
            speech_samples = read_wav_samples(wav_path)
            n_frames = len(speech_samples)

            amb_name = seg.get("ambiance", "none")
            sfx_name = seg.get("sfx", "none")
            amb_samples = fx_cache.get(("amb", amb_name), [])
            sfx_samples = fx_cache.get(("sfx", sfx_name), [])

            mixed_bytes = mix_fx(speech_samples, amb_samples, sfx_samples)
            out_w.writeframes(mixed_bytes)

            for ev in evs:
                all_events.append({
                    "text": ev["text"],
                    "offset": ev["offset"] + cum_ticks,
                    "duration": ev["duration"],
                })

            begin_sec = round(cum_frames / SAMPLE_RATE, 3)
            end_sec = round((cum_frames + n_frames) / SAMPLE_RATE, 3)
            seg_metas.append({
                "segIdx": idx,
                "role": seg.get("role", "narrator"),
                "voice": seg.get("voice", "en-GB-SoniaNeural"),
                "emotion": seg.get("emotion", "neutral"),
                "rate": seg.get("rate", "+0%"),
                "pitch": seg.get("pitch", "+0Hz"),
                "volume": seg.get("volume", "+0%"),
                "ambiance": amb_name,
                "sfx": sfx_name,
                "confidence": seg.get("confidence", "high"),
                "beginSec": begin_sec,
                "endSec": end_sec,
                "text": seg["text"],
            })

            cum_frames += n_frames
            if idx < len(results) - 1:
                out_w.writeframes(GAP_BYTES)
                cum_frames += GAP_FRAMES

    m4a_path = audio_m4a_dir / f"ch{ch_idx:02d}.m4a"
    subprocess.run(
        ["afconvert", "-f", "m4af", "-d", "aac", "-c", "2", "-b", "64000", str(full_wav), str(m4a_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (docs_audio_dir / f"ch{ch_idx:02d}.m4a").write_bytes(m4a_path.read_bytes())
    (audio_dir / f"ch{ch_idx:02d}.events.json").write_text(json.dumps(all_events), encoding="utf-8")
    (audio_dir / f"ch{ch_idx:02d}.segments_meta.json").write_text(json.dumps(seg_metas), encoding="utf-8")

    print(f"Ch {ch_idx:02d} mixed: {len(segs)} segments, {len(all_events)} words, {cum_frames / SAMPLE_RATE:.1f}s")


async def async_main(project_dir: Path):
    script_path = project_dir / "studio" / "cast_script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing {script_path}. Run generate_cast_script.py first.")
    script_data = json.loads(script_path.read_text(encoding="utf-8"))

    fx_dir = project_dir / "assets" / "audio_fx"
    fx_cache = {}
    for p in (fx_dir / "ambiance").glob("*.wav") if (fx_dir / "ambiance").exists() else []:
        fx_cache[("amb", p.stem)] = read_wav_samples(p)
    for p in (fx_dir / "sfx").glob("*.wav") if (fx_dir / "sfx").exists() else []:
        fx_cache[("sfx", p.stem)] = read_wav_samples(p)

    for ch_idx, ch_data in enumerate(script_data["chapters"], 1):
        await process_chapter(ch_idx, ch_data, project_dir, fx_cache)


def main():
    ap = argparse.ArgumentParser(description="Synthesize multi-voice narration with emotion, ambiance, and SFX")
    ap.add_argument("--project-dir", required=True, help="Project root containing studio/cast_script.json")
    args = ap.parse_args()
    asyncio.run(async_main(Path(args.project_dir).resolve()))


if __name__ == "__main__":
    main()
