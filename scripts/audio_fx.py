#!/usr/bin/env python3
"""Generate clean, copyright-free 24 kHz 16-bit mono WAV ambiance beds and spot SFX."""

import argparse
import math
import random
import struct
import wave
from pathlib import Path

SR = 24000


def write_wav(path: Path, samples: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        clamped = [max(-32767, min(32767, int(s * 32767))) for s in samples]
        w.writeframes(struct.pack("<" + "h" * len(clamped), *clamped))


def lowpass(samples: list, alpha: float) -> list:
    out = []
    y = 0.0
    for x in samples:
        y = y + alpha * (x - y)
        out.append(y)
    return out


def gen_fireplace(dur: float = 8.0) -> list:
    n = int(SR * dur)
    rng = random.Random(42)
    rumble = lowpass([rng.uniform(-0.35, 0.35) for _ in range(n)], 0.03)
    out = list(rumble)
    # Random warm crackles
    for _ in range(int(dur * 14)):
        pos = rng.randint(0, n - 400)
        amp = rng.uniform(0.15, 0.55)
        for k in range(rng.randint(80, 260)):
            out[pos + k] += amp * math.exp(-k / 40.0) * rng.uniform(-1, 1)
    return out


def gen_winter_wind(dur: float = 8.0) -> list:
    n = int(SR * dur)
    rng = random.Random(7)
    noise = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    wind = lowpass(noise, 0.025)
    out = []
    for i, x in enumerate(wind):
        t = i / SR
        mod = 0.45 + 0.45 * math.sin(2 * math.pi * t / 3.5) + 0.1 * math.sin(2 * math.pi * t / 1.3)
        whistle = 0.06 * mod * math.sin(2 * math.pi * (280 + 70 * math.sin(2 * math.pi * t / 4.0)) * t)
        out.append(x * mod * 1.4 + whistle)
    return out


def gen_spooky_manor(dur: float = 8.0) -> list:
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        drone = 0.25 * math.sin(2 * math.pi * 55 * t) + 0.15 * math.sin(2 * math.pi * 82.4 * t)
        shimmer = 0.08 * math.sin(2 * math.pi * (110 + 1.5 * math.sin(2 * math.pi * t / 2.0)) * t)
        out.append(drone + shimmer)
    return out


def gen_clock_ticking(dur: float = 4.0) -> list:
    n = int(SR * dur)
    out = [0.0] * n
    rng = random.Random(11)
    for beat in range(int(dur * 2)):
        pos = int(beat * 0.5 * SR)
        freq = 1400 if beat % 2 == 0 else 1050
        for k in range(min(900, n - pos)):
            env = math.exp(-k / 90.0)
            out[pos + k] += 0.45 * env * (math.sin(2 * math.pi * freq * k / SR) + 0.3 * rng.uniform(-1, 1))
    return out


def gen_festive_bells(dur: float = 6.0) -> list:
    n = int(SR * dur)
    out = [0.0] * n
    notes = [523.25, 659.25, 783.99, 1046.5]
    for idx, f in enumerate(notes):
        pos = int(idx * 1.4 * SR)
        for k in range(min(int(SR * 2.2), n - pos)):
            t = k / SR
            env = math.exp(-t * 2.2)
            out[pos + k] += 0.22 * env * (math.sin(2 * math.pi * f * t) + 0.4 * math.sin(2 * math.pi * f * 2.0 * t))
    return out


def gen_sfx_chains() -> list:
    n = int(SR * 1.3)
    rng = random.Random(99)
    out = [0.0] * n
    for burst in range(7):
        pos = int(burst * 0.16 * SR)
        for k in range(min(3200, n - pos)):
            t = k / SR
            env = math.exp(-t * 14.0)
            clink = math.sin(2 * math.pi * (1800 + burst * 170) * t) + math.sin(2 * math.pi * 2750 * t)
            out[pos + k] += 0.28 * env * (0.6 * clink + 0.4 * rng.uniform(-1, 1))
    return out


def gen_sfx_door_creak() -> list:
    n = int(SR * 1.1)
    out = []
    for i in range(n):
        t = i / SR
        env = math.sin(math.pi * t / 1.1)
        f = 190 + 95 * math.sin(2 * math.pi * t * 1.8)
        sig = math.sin(2 * math.pi * f * t) + 0.5 * math.sin(2 * math.pi * f * 2.03 * t)
        out.append(0.28 * env * sig)
    return out


def gen_sfx_bell_chime() -> list:
    n = int(SR * 2.2)
    out = []
    for i in range(n):
        t = i / SR
        env = math.exp(-t * 1.8)
        sig = 0.5 * math.sin(2 * math.pi * 220 * t) + 0.35 * math.sin(2 * math.pi * 440 * t) + 0.2 * math.sin(2 * math.pi * 659 * t)
        out.append(0.45 * env * sig)
    return out


def gen_sfx_footsteps() -> list:
    n = int(SR * 1.2)
    rng = random.Random(21)
    out = [0.0] * n
    for step in range(3):
        pos = int(step * 0.38 * SR)
        raw = lowpass([rng.uniform(-1, 1) for _ in range(1800)], 0.18)
        for k, val in enumerate(raw):
            if pos + k < n:
                out[pos + k] += 0.65 * val * math.exp(-k / 350.0)
    return out


def gen_sfx_thunder() -> list:
    n = int(SR * 2.4)
    rng = random.Random(33)
    rumble = lowpass([rng.uniform(-1, 1) for _ in range(n)], 0.02)
    return [val * 1.8 * math.exp(-(i / SR) * 1.1) * min(1.0, (i / SR) * 12) for i, val in enumerate(rumble)]


def gen_sfx_knocker() -> list:
    n = int(SR * 0.8)
    out = [0.0] * n
    for knock in (0, int(0.28 * SR)):
        for k in range(min(3000, n - knock)):
            t = k / SR
            out[knock + k] += 0.55 * math.exp(-t * 22.0) * math.sin(2 * math.pi * 135 * t)
    return out


def main():
    ap = argparse.ArgumentParser(description="Generate procedural 24kHz WAV ambiance & SFX assets")
    ap.add_argument("--out-dir", required=True, help="Output directory for ambiance/ and sfx/")
    args = ap.parse_args()

    out = Path(args.out_dir)
    amb = out / "ambiance"
    sfx = out / "sfx"

    write_wav(amb / "cozy_fireplace.wav", gen_fireplace())
    write_wav(amb / "winter_wind.wav", gen_winter_wind())
    write_wav(amb / "spooky_manor.wav", gen_spooky_manor())
    write_wav(amb / "clock_ticking.wav", gen_clock_ticking())
    write_wav(amb / "festive_bells.wav", gen_festive_bells())

    write_wav(sfx / "chains_rattle.wav", gen_sfx_chains())
    write_wav(sfx / "door_creak.wav", gen_sfx_door_creak())
    write_wav(sfx / "bell_chime.wav", gen_sfx_bell_chime())
    write_wav(sfx / "footsteps.wav", gen_sfx_footsteps())
    write_wav(sfx / "thunder.wav", gen_sfx_thunder())
    write_wav(sfx / "knocker.wav", gen_sfx_knocker())

    print(f"Generated 5 ambiance beds & 6 spot SFX in {out}")


if __name__ == "__main__":
    main()
