"""
unified_transcript_builder.py — Single-file unified transcript generator.

Reads the JSONL transcript log (transcript_current_session.json) and produces
one self-contained JSON file with:
  - session_metadata   : session-level summary (platform, user, timing, counts)
  - conversation       : chronological user ↔ bot exchange, both directions
  - summary            : detection rates, FP/FN estimates, pattern analysis

The output is designed to be pasted into a single context window (e.g. GitHub
Copilot Chat) to give full conversation context without needing multiple files.

Usage (CLI):
    python unified_transcript_builder.py --generate
    python unified_transcript_builder.py --generate --transcript path/to/session.json
    python unified_transcript_builder.py --generate --output my_transcript.json
    python unified_transcript_builder.py --summary
    python unified_transcript_builder.py --analyze
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TRANSCRIPT_DIR: str = os.getenv("TRANSCRIPT_DIR", ".")
SESSION_FILE: str = os.path.join(TRANSCRIPT_DIR, "transcript_current_session.json")
DEFAULT_OUTPUT: str = os.path.join(TRANSCRIPT_DIR, "transcript_unified.json")

# False-positive heuristic thresholds (shared across all analysis helpers)
_FP_MAX_CONFIDENCE: float = 0.5
_FP_SHORT_MSG_CHARS: int = 20
_FP_QUESTION_STARTERS = (
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


def _load_session_metadata(transcript_file: str = SESSION_FILE) -> dict:
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
# False-positive / false-negative heuristics
# ---------------------------------------------------------------------------

def _annotate_entries(entries: list[dict]) -> list[dict]:
    """Return a copy of *entries* each annotated with an 'analysis' block."""
    result = []
    for entry in entries:
        entry = dict(entry)
        msg_raw: str = entry.get("message", {}).get("raw", "")
        detection: dict = entry.get("detection", {})
        patterns: list = detection.get("patterns_matched", [])
        action: str = entry.get("action_taken", "none")

        fp_reasons: list[str] = []

        if action in ("warned_user", "blocked_user") and not patterns:
            fp_reasons.append("action taken with no pattern matches (Ollama/keyword only)")

        low_conf = [m for m in patterns if m.get("confidence", 1.0) < _FP_MAX_CONFIDENCE]
        if low_conf and len(low_conf) == len(patterns):
            fp_reasons.append(
                f"all {len(low_conf)} match(es) have confidence < {_FP_MAX_CONFIDENCE}"
            )

        if len(msg_raw.strip()) < _FP_SHORT_MSG_CHARS and patterns:
            fp_reasons.append(f"message is very short ({len(msg_raw.strip())} chars)")

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
        }
        result.append(entry)
    return result


def _pattern_effectiveness(entries: list[dict]) -> list[dict]:
    """Analyse every pattern that appears in *entries* and return stats list."""
    stats: dict[str, dict] = defaultdict(lambda: {
        "times_triggered": 0,
        "true_positives": 0,
        "false_positives": 0,
        "confidences": [],
    })
    for entry in entries:
        patterns = entry.get("detection", {}).get("patterns_matched", [])
        is_fp = entry.get("analysis", {}).get("is_false_positive", False)
        for m in patterns:
            pat = m.get("pattern", "")
            if not pat:
                continue
            stats[pat]["times_triggered"] += 1
            stats[pat]["confidences"].append(m.get("confidence", 0.0))
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
# Conversation turn builders
# ---------------------------------------------------------------------------

def _bot_timestamp(user_ts: str, response_time_ms: float) -> str:
    """Estimate the bot-response timestamp from user timestamp + latency."""
    try:
        t = datetime.fromisoformat(user_ts.replace("Z", "+00:00"))
        t += timedelta(milliseconds=response_time_ms)
        return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except (ValueError, AttributeError):
        return user_ts


def _user_turn(seq: int, entry: dict) -> dict:
    """Build the user-message conversation item from a raw JSONL entry."""
    msg = entry.get("message", {})
    det = entry.get("detection", {})
    hos = entry.get("hostility", {})
    intent_cls = entry.get("intent_classification", {})

    # Derive overall detection confidence from max of individual match confidences
    all_confs = [m.get("confidence", 0.0) for m in det.get("patterns_matched", [])]
    overall_confidence = round(max(all_confs), 4) if all_confs else 0.0
    severity_level = hos.get("severity_level", "none")

    return {
        "sequence": seq,
        "direction": "in",
        "role": "user",
        "timestamp": entry.get("timestamp", ""),
        "message": msg.get("raw", ""),
        "intent": {
            "category": intent_cls.get("category", "neutral"),
            "confidence": intent_cls.get("confidence", 0.0),
            "explanation": intent_cls.get("explanation", ""),
            "tone_markers": intent_cls.get("tone_markers", []),
            "recommended_response": intent_cls.get("recommended_response", ""),
        },
        "detection": {
            "patterns_matched": det.get("patterns_matched", []),
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
                else hos.get("score_after", 0) - hos.get("score_before", 0)
            ),
            "is_escalating": hos.get("score_after", 0) > hos.get("score_before", 0),
            "incident_count": hos.get("incident_count", 0),
        },
        "action_taken": entry.get("action_taken", "none"),
        "analysis": entry.get("analysis", {}),
    }


def _bot_turn(seq: int, entry: dict) -> dict:
    """Build the bot-response conversation item from a raw JSONL entry."""
    resp = entry.get("response", {})
    resp_meta = entry.get("response_metadata", {})
    source = resp_meta.get("source", {})

    user_ts = entry.get("timestamp", "")
    response_time_ms = resp.get("response_time_ms", 0.0)
    bot_ts = _bot_timestamp(user_ts, response_time_ms)

    return {
        "sequence": seq,
        "direction": "out",
        "role": "assistant",
        "timestamp": bot_ts,
        "message": resp.get("chosen", ""),
        "routing_type": resp_meta.get("routing_type", ""),
        "source": {
            "verified_facts": source.get("verified_facts", False),
            "safe_response": source.get("safe_response", False),
            "creative_allowed": source.get("creative_allowed", False),
            "hallucination_risk": source.get("hallucination_risk", "unknown"),
        },
        "template_used": resp.get("template_used", ""),
        "response_time_ms": response_time_ms,
        "routing_explanation": resp_meta.get("explanation", ""),
    }


def _build_conversation(annotated_entries: list[dict]) -> list[dict]:
    """
    Interleave user turns and bot turns into a chronological conversation list.
    Each JSONL entry yields two items: a user turn then a bot turn.
    """
    conversation: list[dict] = []
    seq = 1
    for entry in annotated_entries:
        conversation.append(_user_turn(seq, entry))
        seq += 1
        conversation.append(_bot_turn(seq, entry))
        seq += 1
    return conversation


# ---------------------------------------------------------------------------
# Session metadata builder
# ---------------------------------------------------------------------------

def _build_session_metadata(
    raw_metadata: dict,
    entries: list[dict],
    conversation: list[dict],
) -> dict:
    """Build the top-level session_metadata block."""
    started_at = raw_metadata.get("started_at", "")
    session_id = raw_metadata.get("session_id", "")

    # Use last entry's bot-turn timestamp as end time
    bot_turns = [c for c in conversation if c["role"] == "assistant"]
    if bot_turns:
        end_time = bot_turns[-1]["timestamp"]
    elif entries:
        end_time = entries[-1].get("timestamp", "")
    else:
        end_time = ""

    duration_seconds: Optional[float] = None
    if started_at and end_time:
        try:
            t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration_seconds = round((t1 - t0).total_seconds(), 1)
        except ValueError:
            pass

    platform = entries[0].get("platform", "unknown") if entries else "unknown"
    username = ""
    user_id = ""
    if entries:
        username = entries[0].get("username", "")
        user_id = entries[0].get("user_id", "")

    total_user_messages = len([c for c in conversation if c["role"] == "user"])
    total_bot_responses = len([c for c in conversation if c["role"] == "assistant"])

    return {
        "session_id": session_id,
        "platform": platform,
        "user_id": user_id,
        "username": username,
        "start_time": started_at,
        "end_time": end_time,
        "total_messages": total_user_messages + total_bot_responses,
        "total_user_messages": total_user_messages,
        "total_bot_responses": total_bot_responses,
        "session_duration_seconds": duration_seconds,
    }


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(
    annotated_entries: list[dict],
    conversation: list[dict],
    pat_effectiveness: list[dict],
) -> dict:
    """Build the bottom-level summary / analytics block."""
    user_turns = [c for c in conversation if c["role"] == "user"]
    total = len(user_turns)

    severity_counts: Counter = Counter()
    for turn in user_turns:
        sev = turn["detection"]["overall_severity"]
        severity_counts[sev] += 1

    blocked = sum(1 for t in user_turns if t["action_taken"] == "blocked_user")
    warned = sum(1 for t in user_turns if t["action_taken"] == "warned_user")
    blocking_rate = round(blocked / total * 100, 1) if total else 0.0

    fp_count = sum(1 for e in annotated_entries if e.get("analysis", {}).get("is_false_positive"))
    fn_count = sum(1 for e in annotated_entries if e.get("analysis", {}).get("is_false_negative"))
    fp_estimate = round(fp_count / total * 100, 1) if total else 0.0
    fn_estimate = round(fn_count / total * 100, 1) if total else 0.0

    # Collect unique routing types used by bot turns
    bot_turns = [c for c in conversation if c["role"] == "assistant"]
    routing_counts: Counter = Counter(
        t["routing_type"] for t in bot_turns if t.get("routing_type")
    )

    # User interaction patterns
    user_intents: Counter = Counter(
        t["intent"]["category"] for t in user_turns if t.get("intent", {}).get("category")
    )
    patterns_used: list[str] = sorted({
        m["pattern"]
        for e in annotated_entries
        for m in e.get("detection", {}).get("patterns_matched", [])
        if m.get("pattern")
    })

    # Recommendations
    recommendations: list[str] = []
    high_fp = [p for p in pat_effectiveness if p["false_positive_rate"] >= 50]
    if high_fp:
        recommendations.append(
            "Consider removing or raising the threshold for: "
            + ", ".join(f"'{p['pattern']}'" for p in high_fp[:5])
        )
    low_conf = [p for p in pat_effectiveness if p["confidence_average"] < 0.6]
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
        "total_user_messages": total,
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
        "routing_breakdown": dict(routing_counts),
        "intent_breakdown": dict(user_intents),
        "patterns": patterns_used,
        "pattern_effectiveness": pat_effectiveness,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def build_unified_transcript(
    transcript_file: str = SESSION_FILE,
) -> dict:
    """
    Read the JSONL transcript file and return the full unified transcript dict.

    The returned dict has three top-level keys:
      - ``session_metadata``  — session-level info (platform, user, timing)
      - ``conversation``      — chronological list of user + bot turns
      - ``summary``           — detection stats, FP/FN analysis, recommendations
    """
    raw_entries = _load_entries(transcript_file)
    raw_metadata = _load_session_metadata(transcript_file)

    annotated = _annotate_entries(raw_entries)
    conversation = _build_conversation(annotated)
    pat_eff = _pattern_effectiveness(annotated)

    session_metadata = _build_session_metadata(raw_metadata, raw_entries, conversation)
    summary = _build_summary(annotated, conversation, pat_eff)

    return {
        "session_metadata": session_metadata,
        "conversation": conversation,
        "summary": summary,
    }


def export_unified_transcript(
    transcript_file: str = SESSION_FILE,
    output_path: str = DEFAULT_OUTPUT,
) -> str:
    """
    Generate the unified transcript and write it to *output_path* as JSON.
    Returns the path of the written file.
    """
    data = build_unified_transcript(transcript_file)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return output_path


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _cli_summary(transcript_file: str) -> None:
    data = build_unified_transcript(transcript_file)
    sm = data["session_metadata"]
    su = data["summary"]

    print("=" * 60)
    print("  UNIFIED TRANSCRIPT SUMMARY")
    print("=" * 60)
    display_name = sm["username"] or sm["user_id"] or "unknown"
    print(f"  Session ID         : {sm['session_id']}")
    print(f"  Platform           : {sm['platform']}")
    print(f"  Username           : {display_name}")
    print(f"  Start time         : {sm['start_time']}")
    print(f"  End time           : {sm['end_time']}")
    print(f"  Duration (s)       : {sm['session_duration_seconds']}")
    print(f"  Total messages     : {sm['total_messages']}")
    print(f"  User messages      : {sm['total_user_messages']}")
    print(f"  Bot responses      : {sm['total_bot_responses']}")
    print()
    print("  Severity breakdown:")
    for sev, count in su["detection_rate_by_severity"].items():
        print(f"    {sev:<10}: {count}")
    print()
    print(f"  False-positive est : {su['false_positive_estimate']}%")
    print(f"  False-negative est : {su['false_negative_estimate']}%")
    print(f"  Blocking rate      : {su['blocking_rate']}%")
    print(f"  Warnings issued    : {su['warnings_issued']}")
    print()
    if su["routing_breakdown"]:
        print("  Routing breakdown:")
        for rtype, count in sorted(su["routing_breakdown"].items()):
            print(f"    {rtype:<20}: {count}")
        print()
    print("  Recommendations:")
    for rec in su["recommendations"]:
        print(f"    • {rec}")
    print("=" * 60)


def _cli_analyze(transcript_file: str) -> None:
    raw = _load_entries(transcript_file)
    annotated = _annotate_entries(raw)

    fp_list = [e for e in annotated if e.get("analysis", {}).get("is_false_positive")]
    fn_list = [e for e in annotated if e.get("analysis", {}).get("is_false_negative")]

    print("=" * 60)
    print("  FALSE POSITIVE / NEGATIVE ANALYSIS")
    print("=" * 60)
    print(f"  Total entries     : {len(raw)}")
    print(f"  False positives   : {len(fp_list)}")
    print(f"  False negatives   : {len(fn_list)}")
    if fp_list:
        print()
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _cli_main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Unified Transcript Builder — produce a single JSON file with full "
            "conversation context (user turns + bot responses + analysis)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python unified_transcript_builder.py --generate
  python unified_transcript_builder.py --generate --transcript session.json
  python unified_transcript_builder.py --generate --output my_transcript.json
  python unified_transcript_builder.py --summary
  python unified_transcript_builder.py --analyze
""",
    )
    parser.add_argument(
        "--transcript", default=SESSION_FILE,
        help=f"Path to the JSONL source file (default: {SESSION_FILE})"
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT})"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--generate", action="store_true",
        help="Generate transcript_unified.json from the current session"
    )
    group.add_argument(
        "--summary", action="store_true",
        help="Print a short session summary to stdout"
    )
    group.add_argument(
        "--analyze", action="store_true",
        help="Print false-positive / false-negative analysis to stdout"
    )

    args = parser.parse_args()

    if args.generate:
        out = export_unified_transcript(
            transcript_file=args.transcript,
            output_path=args.output,
        )
        print(f"✅ Unified transcript written to: {out}")
    elif args.summary:
        _cli_summary(args.transcript)
    elif args.analyze:
        _cli_analyze(args.transcript)


if __name__ == "__main__":
    _cli_main()
