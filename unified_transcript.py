"""
unified_transcript.py — Comprehensive unified transcript generator.

Reads the JSONL transcript log (transcript_current_session.json) and produces a
single, well-formatted JSON file containing full session context, all detection
data, false-positive flags, and pattern-effectiveness analysis.

Usage (CLI):
    python unified_transcript.py --generate
    python unified_transcript.py --analyze
    python unified_transcript.py --export
    python unified_transcript.py --summary
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Re-use the same defaults as transcript_logger
# ---------------------------------------------------------------------------

TRANSCRIPT_DIR: str = os.getenv("TRANSCRIPT_DIR", ".")
SESSION_FILE: str = os.path.join(TRANSCRIPT_DIR, "transcript_current_session.json")

# False-positive heuristics
# _FP_MAX_CONFIDENCE is intentionally shared: it marks entries as suspected FPs
# (analyze_false_positives) AND flags individual pattern matches as FPs in
# calculate_pattern_effectiveness, providing a consistent threshold throughout.
_FP_MAX_CONFIDENCE: float = 0.5          # matches below this are suspected FP
_FP_SHORT_MSG_CHARS: int = 20            # very short messages are rarely hostile
_FP_QUESTION_STARTERS = (               # question-style openers unlikely to be attacks
    "who is", "what is", "what are", "how do", "how does", "where is",
    "why is", "can you", "could you", "do you", "does this",
)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def _load_entries(transcript_file: str = SESSION_FILE) -> list[dict]:
    """Load all non-metadata JSONL entries from a transcript file."""
    entries: list[dict] = []
    path = Path(transcript_file)
    if not path.exists():
        return entries
    with open(transcript_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("_type") == "session_metadata":
                    continue
                entries.append(obj)
            except json.JSONDecodeError:
                pass
    return entries


def _load_metadata(transcript_file: str = SESSION_FILE) -> dict:
    """Return the session_metadata object from the JSONL file, or {}."""
    path = Path(transcript_file)
    if not path.exists():
        return {}
    with open(transcript_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("_type") == "session_metadata":
                    return obj
            except json.JSONDecodeError:
                pass
    return {}


# ---------------------------------------------------------------------------
# False-positive analysis
# ---------------------------------------------------------------------------

def analyze_false_positives(entries: list[dict]) -> list[dict]:
    """
    Return a copy of *entries* with an extra 'analysis' block added to each
    entry.  The block contains heuristic false-positive / false-negative flags
    and an explanation.
    """
    result = []
    for entry in entries:
        entry = dict(entry)  # shallow copy
        msg_raw: str = entry.get("message", {}).get("raw", "")
        detection: dict = entry.get("detection", {})
        patterns: list = detection.get("patterns_matched", [])
        action: str = entry.get("action_taken", "none")

        # --- False positive heuristics ---
        fp_reasons: list[str] = []

        # 1. No patterns matched at all but action was still taken
        if action in ("warned_user", "blocked_user") and not patterns:
            fp_reasons.append("action taken with no pattern matches (Ollama/keyword only)")

        # 2. Low-confidence matches
        low_conf_matches = [m for m in patterns if m.get("confidence", 1.0) < _FP_MAX_CONFIDENCE]
        if low_conf_matches and len(low_conf_matches) == len(patterns):
            fp_reasons.append(
                f"all {len(low_conf_matches)} match(es) have confidence < {_FP_MAX_CONFIDENCE}"
            )

        # 3. Very short message
        if len(msg_raw.strip()) < _FP_SHORT_MSG_CHARS and patterns:
            fp_reasons.append(f"message is very short ({len(msg_raw.strip())} chars)")

        # 4. Question-style openers
        msg_lower = msg_raw.lower().strip()
        for starter in _FP_QUESTION_STARTERS:
            if msg_lower.startswith(starter):
                fp_reasons.append(f"message starts with question phrase '{starter}'")
                break

        is_fp = bool(fp_reasons)
        is_fn = (
            not patterns
            and action == "none"
            and any(
                kw in msg_lower
                for kw in ("fuck", "shit", "idiot", "hate you", "scam", "spam")
            )
        )

        # Infer user intent
        if action == "blocked_user":
            user_intent = "troll"
        elif action == "warned_user":
            user_intent = "frustrated"
        elif is_fp:
            user_intent = "genuine"
        else:
            user_intent = "neutral"

        explanation_parts = []
        if is_fp:
            explanation_parts.append("Suspected false positive: " + "; ".join(fp_reasons))
        if is_fn:
            explanation_parts.append(
                "Possible false negative: hostile keywords in message but no detection triggered"
            )
        if not explanation_parts:
            explanation_parts.append("No anomaly detected.")

        entry["analysis"] = {
            "is_false_positive": is_fp,
            "is_false_negative": is_fn,
            "explanation": " | ".join(explanation_parts),
            "user_intent": user_intent,
            "should_have_triggered": bool(patterns) or is_fn,
        }
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Pattern effectiveness
# ---------------------------------------------------------------------------

def calculate_pattern_effectiveness(entries: list[dict]) -> list[dict]:
    """
    Analyse every pattern that appears in *entries* and return a list of dicts:
        pattern, times_triggered, true_positive_rate, false_positive_rate,
        confidence_average, recommendation
    """
    # Accumulate per-pattern stats
    stats: dict[str, dict] = defaultdict(lambda: {
        "times_triggered": 0,
        "true_positives": 0,
        "false_positives": 0,
        "confidences": [],
    })

    for entry in entries:
        patterns = entry.get("detection", {}).get("patterns_matched", [])
        analysis = entry.get("analysis", {})
        is_fp = analysis.get("is_false_positive", False)

        for m in patterns:
            pat = m.get("pattern", "")
            if not pat:
                continue
            conf = m.get("confidence", 0.0)
            stats[pat]["times_triggered"] += 1
            stats[pat]["confidences"].append(conf)
            # A match is counted as a false positive when the whole interaction
            # was flagged as a FP by heuristics.  Low-confidence matches are
            # tracked via average confidence, not as a separate FP counter, to
            # keep the two signals independent.
            if is_fp:
                stats[pat]["false_positives"] += 1
            else:
                stats[pat]["true_positives"] += 1

    result = []
    for pat, s in sorted(stats.items(), key=lambda kv: -kv[1]["times_triggered"]):
        total = s["times_triggered"]
        tp = s["true_positives"]
        fp = s["false_positives"]
        confs = s["confidences"]
        avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.0
        tp_rate = round(tp / total * 100, 1) if total else 0.0
        fp_rate = round(fp / total * 100, 1) if total else 0.0

        if fp_rate >= 50:
            recommendation = "REMOVE or tighten — too many false positives"
        elif avg_conf < 0.6:
            recommendation = "ADJUST threshold — low average confidence"
        elif tp_rate >= 80:
            recommendation = "KEEP — high true-positive rate"
        else:
            recommendation = "MONITOR — mixed signal"

        result.append({
            "pattern": pat,
            "times_triggered": total,
            "true_positive_rate": tp_rate,
            "false_positive_rate": fp_rate,
            "confidence_average": avg_conf,
            "recommendation": recommendation,
        })
    return result


# ---------------------------------------------------------------------------
# Building the unified format
# ---------------------------------------------------------------------------

def _why_triggered(match: dict) -> str:
    """Generate a human-readable explanation for a single pattern match."""
    pattern = match.get("pattern", "?")
    category = match.get("category", "?")
    severity = match.get("severity", "?")
    confidence = match.get("confidence", 0.0)
    matched_token = match.get("matched_token", "")
    pos = match.get("position_in_text", -1)

    parts = [f"Pattern '{pattern}' ({category} / {severity})"]
    if matched_token and matched_token != pattern:
        parts.append(f"matched via variation '{matched_token}'")
    if pos >= 0:
        parts.append(f"found at character offset {pos}")
    if confidence < 1.0:
        parts.append(f"fuzzy match — confidence {confidence:.0%}")
    else:
        parts.append("exact match")
    return " — ".join(parts)


def _build_interaction(seq: int, entry: dict) -> dict:
    """Convert a raw JSONL entry into the unified interaction format."""
    msg = entry.get("message", {})
    det = entry.get("detection", {})
    hos = entry.get("hostility", {})
    resp = entry.get("response", {})
    analysis = entry.get("analysis", {})

    # Enrich patterns_matched with why_triggered
    patterns_matched = []
    for m in det.get("patterns_matched", []):
        pm = dict(m)
        pm["why_triggered"] = _why_triggered(m)
        patterns_matched.append(pm)

    # Derive overall detection confidence as max of individual match confidences
    all_confs = [m.get("confidence", 0.0) for m in det.get("patterns_matched", [])]
    overall_confidence = round(max(all_confs), 4) if all_confs else 0.0

    severity_level = hos.get("severity_level", "none")

    return {
        "sequence": seq,
        "timestamp": entry.get("timestamp", ""),
        "direction": "in",
        "from_user": entry.get("username") or entry.get("user_id", "unknown"),
        "message": msg.get("raw", ""),
        "message_length": msg.get("length", len(msg.get("raw", ""))),
        "detection": {
            "patterns_matched": patterns_matched,
            "leet_speak_conversions": det.get("leet_speak_conversions", []),
            "all_caps": det.get("all_caps", False),
            "all_caps_percentage": round(det.get("all_caps_ratio", 0.0) * 100, 1),
            "via_detector": det.get("via_detector", False),
            "via_ollama": det.get("via_ollama", False),
            "detection_time_ms": det.get("detection_time_ms", 0.0),
            "overall_severity": severity_level,
            "overall_confidence": overall_confidence,
        },
        "hostility": {
            "score_before": hos.get("score_before", 0),
            "score_after": hos.get("score_after", 0),
            "score_delta": (
                hos["score_delta"]
                if "score_delta" in hos
                else (
                    hos["score_after"] - hos["score_before"]
                    if "score_after" in hos and "score_before" in hos
                    else None
                )
            ),
            "is_escalating": hos.get("score_after", 0) > hos.get("score_before", 0),
            "incident_count": hos.get("incident_count", 0),
            "cooldown_active": hos.get("should_block", False),
        },
        "response": {
            "chosen": resp.get("chosen", ""),
            "template_used": resp.get("template_used", ""),
            "response_time_ms": resp.get("response_time_ms", 0.0),
            "reason_for_response": _response_reason(entry),
        },
        "action_taken": entry.get("action_taken", "none"),
        "intent_classification": entry.get("intent_classification", {}),
        "response_metadata": entry.get("response_metadata", {}),
        "analysis": analysis,
    }


def _response_reason(entry: dict) -> str:
    """Generate an explanation of why the bot chose its response."""
    action = entry.get("action_taken", "none")
    hos = entry.get("hostility", {})
    severity = hos.get("severity_level", "none")
    det = entry.get("detection", {})
    via_ollama = det.get("via_ollama", False)
    via_detector = det.get("via_detector", False)
    resp = entry.get("response", {})
    template = resp.get("template_used", "")

    if action == "none":
        return "No hostile signal detected; no response sent."
    method = "Ollama" if via_ollama else ("pattern detector" if via_detector else "keyword fallback")
    action_text = {
        "warned_user": "issued a soft warning",
        "blocked_user": "blocked the user",
    }.get(action, action)
    return (
        f"Severity classified as '{severity}' by {method}; "
        f"bot {action_text} using template '{template}'."
    )


def _build_session(metadata: dict, entries: list[dict], interactions: list[dict]) -> dict:
    """Build the top-level session metadata block."""
    start_time = metadata.get("started_at", "")
    end_time = entries[-1].get("timestamp", "") if entries else ""

    # Try to compute duration
    duration_seconds: Optional[float] = None
    if start_time and end_time:
        try:
            t0 = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration_seconds = round((t1 - t0).total_seconds(), 1)
        except ValueError:
            pass

    users: set[str] = set()
    for e in entries:
        uid = e.get("user_id") or e.get("username")
        if uid:
            users.add(uid)

    total = len(interactions)
    detected = sum(
        1 for i in interactions
        if i["detection"]["patterns_matched"] or i["detection"]["via_ollama"]
    )
    detection_rate = round(detected / total * 100, 1) if total else 0.0

    # Infer platform from first entry
    platform = entries[0].get("platform", "unknown") if entries else "unknown"

    return {
        "start_time": start_time,
        "end_time": end_time,
        "platform": platform,
        "user_id": entries[0].get("user_id", "") if entries else "",
        "username": entries[0].get("username", "") if entries else "",
        "total_messages": total,
        "session_duration_seconds": duration_seconds,
        "total_detection_rate": detection_rate,
    }


def _build_summary(
    entries: list[dict],
    interactions: list[dict],
    fp_entries: list[dict],
    pattern_effectiveness: list[dict],
) -> dict:
    """Build the bottom-level summary / analytics block."""
    total = len(interactions)
    start_ts = interactions[0]["timestamp"] if interactions else ""
    end_ts = interactions[-1]["timestamp"] if interactions else ""

    severity_counts: Counter = Counter()
    for i in interactions:
        sev = i["detection"]["overall_severity"]
        severity_counts[sev] += 1

    blocked = sum(1 for i in interactions if i["action_taken"] == "blocked_user")
    warned = sum(1 for i in interactions if i["action_taken"] == "warned_user")
    blocking_rate = round(blocked / total * 100, 1) if total else 0.0

    fp_count = sum(1 for e in fp_entries if e.get("analysis", {}).get("is_false_positive"))
    fn_count = sum(1 for e in fp_entries if e.get("analysis", {}).get("is_false_negative"))
    fp_estimate = round(fp_count / total * 100, 1) if total else 0.0
    fn_estimate = round(fn_count / total * 100, 1) if total else 0.0

    users_involved = sorted({
        i.get("from_user", "") for i in interactions if i.get("from_user")
    })

    # Recommendations
    recommendations: list[str] = []
    high_fp = [p for p in pattern_effectiveness if p["false_positive_rate"] >= 50]
    if high_fp:
        recommendations.append(
            "Consider removing or raising the threshold for: "
            + ", ".join(f"'{p['pattern']}'" for p in high_fp[:5])
        )
    low_conf = [p for p in pattern_effectiveness if p["confidence_average"] < 0.6]
    if low_conf:
        recommendations.append(
            "Low-confidence patterns to review: "
            + ", ".join(f"'{p['pattern']}'" for p in low_conf[:5])
        )
    if fp_estimate > 20:
        recommendations.append(
            f"Overall false-positive rate is {fp_estimate}% — consider raising minimum confidence threshold."
        )
    if not recommendations:
        recommendations.append("Detection performance looks healthy. Keep monitoring.")

    return {
        "total_entries": total,
        "time_range": f"{start_ts} to {end_ts}",
        "detection_rate_by_severity": {
            "none": severity_counts.get("none", 0),
            "mild": severity_counts.get("mild", 0),
            "moderate": severity_counts.get("moderate", 0),
            "severe": severity_counts.get("severe", 0),
            "threat": severity_counts.get("threat", 0),
        },
        "false_positive_estimate": fp_estimate,
        "false_negative_estimate": fn_estimate,
        "blocking_rate": blocking_rate,
        "warnings_issued": warned,
        "users_involved": users_involved,
        "pattern_effectiveness": pattern_effectiveness,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def generate_unified_transcript(
    transcript_file: str = SESSION_FILE,
) -> dict:
    """
    Read the JSONL transcript file and return the full unified transcript dict.
    Includes session metadata, every interaction with enriched context,
    false-positive analysis, and a summary section.
    """
    raw_entries = _load_entries(transcript_file)
    metadata = _load_metadata(transcript_file)

    # Add analysis block to each entry
    analysed_entries = analyze_false_positives(raw_entries)

    # Build per-interaction records
    interactions = [
        _build_interaction(seq, entry)
        for seq, entry in enumerate(analysed_entries, start=1)
    ]

    # Pattern effectiveness (needs analysis blocks populated first)
    pattern_effectiveness = calculate_pattern_effectiveness(analysed_entries)

    session = _build_session(metadata, raw_entries, interactions)
    summary = _build_summary(raw_entries, interactions, analysed_entries, pattern_effectiveness)

    return {
        "session": session,
        "interactions": interactions,
        "summary": summary,
    }


def export_to_json(
    transcript_file: str = SESSION_FILE,
    output_path: str = "",
) -> str:
    """
    Generate the unified transcript and write it to a timestamped JSON file.
    Returns the path of the written file.
    """
    data = generate_unified_transcript(transcript_file)

    if not output_path:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        output_path = f"unified_transcript_{ts}.json"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return output_path


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _print_summary(transcript_file: str) -> None:
    data = generate_unified_transcript(transcript_file)
    session = data["session"]
    summary = data["summary"]

    print("=" * 60)
    print("  UNIFIED TRANSCRIPT SUMMARY")
    print("=" * 60)
    print(f"  Platform           : {session['platform']}")
    print(f"  Session start      : {session['start_time']}")
    print(f"  Session end        : {session['end_time']}")
    print(f"  Duration (s)       : {session['session_duration_seconds']}")
    print(f"  Total messages     : {session['total_messages']}")
    print(f"  Detection rate     : {session['total_detection_rate']}%")
    print(f"  Blocking rate      : {summary['blocking_rate']}%")
    print(f"  Warnings issued    : {summary['warnings_issued']}")
    print(f"  FP estimate        : {summary['false_positive_estimate']}%")
    print(f"  FN estimate        : {summary['false_negative_estimate']}%")
    print()
    print("  Severity breakdown:")
    for sev, count in summary["detection_rate_by_severity"].items():
        print(f"    {sev:<10}: {count}")
    print()
    print("  Recommendations:")
    for rec in summary["recommendations"]:
        print(f"    • {rec}")
    print("=" * 60)


def _print_analysis(transcript_file: str) -> None:
    raw = _load_entries(transcript_file)
    analysed = analyze_false_positives(raw)

    fp_list = [e for e in analysed if e.get("analysis", {}).get("is_false_positive")]
    fn_list = [e for e in analysed if e.get("analysis", {}).get("is_false_negative")]

    print("=" * 60)
    print("  FALSE POSITIVE / NEGATIVE ANALYSIS")
    print("=" * 60)
    print(f"  Total entries     : {len(raw)}")
    print(f"  False positives   : {len(fp_list)}")
    print(f"  False negatives   : {len(fn_list)}")
    print()
    if fp_list:
        print("  Suspected false positives:")
        for e in fp_list[:10]:
            msg = e.get("message", {}).get("raw", "")[:60]
            expl = e.get("analysis", {}).get("explanation", "")
            print(f"    ✗ {msg!r}")
            print(f"      → {expl}")
    if fn_list:
        print()
        print("  Possible false negatives:")
        for e in fn_list[:10]:
            msg = e.get("message", {}).get("raw", "")[:60]
            expl = e.get("analysis", {}).get("explanation", "")
            print(f"    ✗ {msg!r}")
            print(f"      → {expl}")
    print("=" * 60)


def _print_pattern_effectiveness(transcript_file: str) -> None:
    raw = _load_entries(transcript_file)
    analysed = analyze_false_positives(raw)
    effectiveness = calculate_pattern_effectiveness(analysed)

    print("=" * 60)
    print("  PATTERN EFFECTIVENESS")
    print("=" * 60)
    if not effectiveness:
        print("  No pattern data available.")
    for p in effectiveness:
        print(
            f"  {p['pattern']:<40} "
            f"hits={p['times_triggered']:>4}  "
            f"TP={p['true_positive_rate']:>5.1f}%  "
            f"FP={p['false_positive_rate']:>5.1f}%  "
            f"conf={p['confidence_average']:.3f}  "
            f"→ {p['recommendation']}"
        )
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified Transcript Generator — produce comprehensive JSON analysis files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python unified_transcript.py --generate
  python unified_transcript.py --generate --transcript path/to/session.json --output out.json
  python unified_transcript.py --analyze
  python unified_transcript.py --export
  python unified_transcript.py --summary
""",
    )
    parser.add_argument(
        "--transcript", default=SESSION_FILE,
        help=f"Path to the JSONL transcript file (default: {SESSION_FILE})"
    )
    parser.add_argument(
        "--output", default="",
        help="Output file path for --generate/--export (default: auto-timestamped)"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--generate", action="store_true",
        help="Generate the unified transcript JSON file"
    )
    group.add_argument(
        "--analyze", action="store_true",
        help="Print false-positive / false-negative analysis to stdout"
    )
    group.add_argument(
        "--export", action="store_true",
        help="Alias for --generate (write unified JSON to file)"
    )
    group.add_argument(
        "--summary", action="store_true",
        help="Print a short summary report to stdout"
    )
    group.add_argument(
        "--patterns", action="store_true",
        help="Print pattern effectiveness table to stdout"
    )

    args = parser.parse_args()

    if args.generate or args.export:
        out = export_to_json(transcript_file=args.transcript, output_path=args.output)
        print(f"✅ Unified transcript written to: {out}")
    elif args.analyze:
        _print_analysis(args.transcript)
    elif args.summary:
        _print_summary(args.transcript)
    elif args.patterns:
        _print_pattern_effectiveness(args.transcript)


if __name__ == "__main__":
    _cli_main()
