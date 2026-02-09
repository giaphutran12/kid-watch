#!/usr/bin/env python3
"""
Analyze video keyframes using Gemini API for activity classification.

Sends keyframe images to Gemini 3 Flash Preview for activity analysis and produces
a timeline of what the person is doing in the video.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types


def load_env(path: str = ".env") -> Dict[str, str]:
    """Read .env file and return dict of key=value pairs."""
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    # Strip quotes
                    value = value.strip().strip('"').strip("'")
                    env[key.strip()] = value
    except FileNotFoundError:
        print(f"[ERROR] .env file not found at {path}")
        sys.exit(1)
    return env


def parse_timestamp(filename: str) -> Optional[tuple[int, int]]:
    """
    Parse timestamp from filename like 'frame_09_17.jpg' -> (9, 17).
    Returns (minutes, seconds) or None if parsing fails.
    """
    match = re.match(r"(?:small_)?frame_(\d+)_(\d+)\.jpg", filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def format_time(minutes: int, seconds: int) -> str:
    """Format time as MM:SS."""
    return f"{minutes}:{seconds:02d}"


def get_keyframe_files(keyframes_dir: str) -> List[tuple[str, int, int]]:
    """
    Get all keyframe files sorted by timestamp.
    Returns list of (filename, minutes, seconds) tuples.
    """
    keyframes = []
    keyframes_path = Path(keyframes_dir)

    if not keyframes_path.exists():
        print(f"[ERROR] Keyframes directory not found: {keyframes_dir}")
        sys.exit(1)

    # Prefer small_frame_* files if available, otherwise use frame_* files
    for file in keyframes_path.glob("small_frame_*.jpg"):
        ts = parse_timestamp(file.name)
        if ts:
            keyframes.append((file.name, ts[0], ts[1]))

    # Add regular frames that don't have small versions
    small_frames = {
        f.name.replace("small_", "") for f in keyframes_path.glob("small_frame_*.jpg")
    }
    for file in keyframes_path.glob("frame_*.jpg"):
        if file.name not in small_frames:
            ts = parse_timestamp(file.name)
            if ts:
                keyframes.append((file.name, ts[0], ts[1]))

    # Sort by timestamp
    keyframes.sort(key=lambda x: (x[1], x[2]))
    return keyframes


def analyze_keyframe(
    client: genai.Client,
    image_path: str,
    model: str,
    delay: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """
    Send a keyframe to Gemini API for analysis.
    Returns parsed JSON response or None on error.
    """
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        prompt = """Analyze this image from a study monitoring camera. Classify the person's activity.

Respond in EXACTLY this JSON format (no markdown, no explanation):
{
  "activity": "STUDYING" | "SLOUCHING" | "DISTRACTED" | "PHONE" | "ABSENT" | "LYING_DOWN" | "UNKNOWN",
  "posture": "good" | "slightly_slouched" | "heavily_slouched" | "leaning_back" | "lying_down" | "not_visible",
  "gaze": "at_desk" | "at_screen" | "looking_away" | "looking_at_phone" | "not_visible",
  "phone_visible": true | false,
  "phone_in_hand": true | false,
  "person_at_desk": true | false,
  "person_visible": true | false,
  "confidence": 0.0-1.0,
  "description": "Brief 1-sentence description of what you see"
}

Context: Camera is positioned to the left of the person. The person is typically studying at a desk with a book. The setup is a home environment."""

        response = client.models.generate_content(
            model=model,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            ],
        )

        # Parse JSON from response
        response_text = response.text.strip()
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text)
        time.sleep(delay)
        return result

    except FileNotFoundError:
        print(f"[WARN] Image file not found: {image_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"[WARN] Failed to parse JSON response: {e}")
        print(f"       Raw response: {response_text[:100]}")
        return None
    except Exception as e:
        print(f"[WARN] API error: {e}")
        return None


def format_table(results: List[Dict[str, Any]]) -> str:
    """Format results as a pretty ASCII table."""
    if not results:
        return "No results to display"

    # Calculate column widths
    col_widths = {
        "time": max(6, max(len(r["time"]) for r in results)),
        "activity": max(10, max(len(r.get("activity", "UNKNOWN")) for r in results)),
        "posture": max(10, max(len(r.get("posture", "unknown")) for r in results)),
        "phone": max(
            8, max(len("yes" if r.get("phone_visible") else "no") for r in results)
        ),
        "description": max(
            30, max(len(r.get("description", "")[:30]) for r in results)
        ),
    }

    # Build table
    lines = []
    # Header
    lines.append(
        f"╔═{col_widths['time']=}═╦═{col_widths['activity']=}═╦═{col_widths['posture']=}═╦═{col_widths['phone']=}═╦═{col_widths['description']=}═╗"
    )
    lines[0] = (
        f"╔{'═' * (col_widths['time'] + 2)}╦{'═' * (col_widths['activity'] + 2)}╦"
        f"{'═' * (col_widths['posture'] + 2)}╦{'═' * (col_widths['phone'] + 2)}╦"
        f"{'═' * (col_widths['description'] + 2)}╗"
    )

    header = (
        f"║ {'Time'.ljust(col_widths['time'])} ║ {'Activity'.ljust(col_widths['activity'])} ║ "
        f"{'Posture'.ljust(col_widths['posture'])} ║ {'Phone'.ljust(col_widths['phone'])} ║ "
        f"{'Description'.ljust(col_widths['description'])} ║"
    )
    lines.append(header)

    # Separator
    sep = (
        f"╠{'═' * (col_widths['time'] + 2)}╬{'═' * (col_widths['activity'] + 2)}╬"
        f"{'═' * (col_widths['posture'] + 2)}╬{'═' * (col_widths['phone'] + 2)}╬"
        f"{'═' * (col_widths['description'] + 2)}╣"
    )
    lines.append(sep)

    # Rows
    for r in results:
        phone_str = "yes" if r.get("phone_visible") else "no"
        desc = r.get("description", "")[: col_widths["description"]]
        row = (
            f"║ {r['time'].ljust(col_widths['time'])} ║ "
            f"{r.get('activity', 'UNKNOWN').ljust(col_widths['activity'])} ║ "
            f"{r.get('posture', 'unknown').ljust(col_widths['posture'])} ║ "
            f"{phone_str.ljust(col_widths['phone'])} ║ "
            f"{desc.ljust(col_widths['description'])} ║"
        )
        lines.append(row)

    # Footer
    footer = (
        f"╚{'═' * (col_widths['time'] + 2)}╩{'═' * (col_widths['activity'] + 2)}╩"
        f"{'═' * (col_widths['posture'] + 2)}╩{'═' * (col_widths['phone'] + 2)}╩"
        f"{'═' * (col_widths['description'] + 2)}╝"
    )
    lines.append(footer)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze video keyframes using Gemini API for activity classification"
    )
    parser.add_argument(
        "--keyframes-dir",
        required=True,
        help="Directory with frame_MM_SS.jpg files",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: {keyframes-dir}/gemini_analysis.json)",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file with GEMINI_API_KEY",
    )
    parser.add_argument(
        "--model",
        default="gemini-3-flash-preview",
        help="Gemini model to use",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between API calls in seconds",
    )

    args = parser.parse_args()

    # Load environment
    env = load_env(args.env_file)
    api_key = env.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not found in .env file")
        sys.exit(1)

    # Initialize Gemini client
    client = genai.Client(api_key=api_key)

    # Get keyframes
    keyframes = get_keyframe_files(args.keyframes_dir)
    if not keyframes:
        print(f"[ERROR] No keyframes found in {args.keyframes_dir}")
        sys.exit(1)

    print(f"[INFO] Found {len(keyframes)} keyframes")

    # Analyze each keyframe
    results = []
    for i, (filename, minutes, seconds) in enumerate(keyframes, 1):
        time_str = format_time(minutes, seconds)
        image_path = os.path.join(args.keyframes_dir, filename)

        print(f"[GEMINI] Analyzing {filename} ({time_str})... ({i}/{len(keyframes)})")

        analysis = analyze_keyframe(client, image_path, args.model, args.delay)
        if analysis:
            analysis["time"] = time_str
            analysis["filename"] = filename
            results.append(analysis)
        else:
            print(f"[WARN] Skipping {filename}")

    # Determine output path
    if args.output is None:
        output_path = os.path.join(args.keyframes_dir, "gemini_analysis.json")
    else:
        output_path = args.output

    # Save JSON results
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[INFO] Saved analysis to {output_path}")

    # Print summary table
    print("\n" + format_table(results))

    # Print statistics
    if results:
        activities = [r.get("activity") for r in results]
        print(f"\n[STATS] Total frames: {len(results)}")
        print(f"[STATS] Activity breakdown:")
        for activity in sorted(set(activities)):
            count = activities.count(activity)
            pct = (count / len(results)) * 100
            print(f"        {activity}: {count} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
