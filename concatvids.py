#!/usr/bin/env python3
"""Shuffle and join MP4 clips on a canvas large enough for every clip."""

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    info = json.loads(result.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"{path}: no video stream")

    rotation = int(video.get("tags", {}).get("rotate", 0))
    for side_data in video.get("side_data_list", []):
        if "rotation" in side_data:
            rotation = int(side_data["rotation"])
    width, height = video["width"], video["height"]
    if rotation % 180:
        width, height = height, width
    sar = video.get("sample_aspect_ratio", "1:1")
    try:
        ratio = Fraction(sar.replace(":", "/"))
        if ratio <= 0:
            ratio = Fraction(1)
    except (ValueError, ZeroDivisionError):
        ratio = Fraction(1)
    duration = float(video.get("duration") or info["format"].get("duration") or 0)
    return math.ceil(width * ratio), height, any(
        s["codec_type"] == "audio" for s in info["streams"]
    ), duration


def gpu_available():
    if not shutil.which("nvidia-smi"):
        return False
    return subprocess.run(
        ["nvidia-smi", "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, help="MP4 clips (default: shuffled *.mp4 in this directory)")
    parser.add_argument("-o", "--output", type=Path, default=Path("all.mp4"))
    parser.add_argument("--cpu", action="store_true", help="encode with libx264 instead of NVIDIA NVENC")
    args = parser.parse_args()

    output = args.output.resolve()
    files = args.files or list(Path.cwd().glob("*.mp4"))
    files = [p.resolve() for p in files if p.resolve() != output]
    if not args.files:
        random.shuffle(files)
    if not files:
        parser.error("no input MP4 files found")
    if any(not p.is_file() for p in files):
        parser.error("all inputs must be existing files")

    details = [probe(p) for p in files]
    width = max(item[0] for item in details)
    height = max(item[1] for item in details)
    # H.264 with widely supported 4:2:0 video needs even dimensions.
    canvas_width = width + width % 2
    canvas_height = height + height % 2
    if (width, height) != (canvas_width, canvas_height):
        print(f"Canvas rounded to {canvas_width}x{canvas_height} for H.264 4:2:0", file=sys.stderr)

    command = ["ffmpeg", "-hide_banner", "-y"]
    for path in files:
        command += ["-i", str(path)]
    audio_inputs = []
    next_input = len(files)
    for _, _, has_audio, duration in details:
        if has_audio:
            audio_inputs.append(None)
        else:
            if duration <= 0:
                raise ValueError("Cannot determine duration for a clip without audio")
            audio_inputs.append(next_input)
            next_input += 1
            command += ["-f", "lavfi", "-t", str(duration), "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=48000"]

    filters = []
    for i, audio_input in enumerate(audio_inputs):
        filters.append(
            f"[{i}:v:0]"
            "scale=w='max(2,ceil(iw*sar/2)*2)':h=ih,setsar=1,"
            f"scale=w={canvas_width}:h={canvas_height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={canvas_width}:{canvas_height}:(ow-iw)/2:(oh-ih)/2:black,"
            "setsar=1,settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p"
            f"[v{i}]"
        )
        source = f"{i}:a:0" if audio_input is None else f"{audio_input}:a:0"
        filters.append(
            f"[{source}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
    filters.append(
        "".join(f"[v{i}][a{i}]" for i in range(len(files)))
        + f"concat=n={len(files)}:v=1:a=1[v][a]"
    )

    use_gpu = not args.cpu and gpu_available()
    encoder = ["-c:v", "h264_nvenc", "-cq", "19", "-b:v", "0"] if use_gpu else [
        "-c:v", "libx264", "-crf", "18", "-preset", "medium"
    ]
    print(f"Joining {len(files)} clips at {canvas_width}x{canvas_height} with {encoder[1]}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        temporary = Path(directory) / "output.mp4"
        command += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                    "-fps_mode", "vfr", *encoder, "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(temporary)]
        subprocess.run(command, check=True)
        temporary.replace(output)
    print(output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
