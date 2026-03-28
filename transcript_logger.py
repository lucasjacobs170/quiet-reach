"""
transcript_logger.py — Structured JSON transcript logging for insult/hostility detection.

Captures every message interaction with full context for fine-tuning and analysis.

Usage (standalone CLI):
    python transcript_logger.py --report summary
    python transcript_logger.py --report patterns --top 20
    python transcript_logger.py --report user_journey --user "username"
    python transcript_logger.py --export html --output report.html
    python transcript_logger.py --export csv --filter "severity:severe" --output severe.csv
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TRANSCRIPT_DIR: str = os.getenv("TRANSCRIPT_DIR", ".")
SESSION_FILE: str = os.path.join(TRANSCRIPT_DIR, "transcript_current_session.json")

# Rotate when the session file exceeds this many entries
ROTATION_LIMIT: int = int(os.getenv("TRANSCRIPT_ROTATION_LIMIT", "1000"))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TranscriptEntry:
    timestamp: str
    session_id: str
    user_id: str
    platform: str
    message: dict          # raw, normalized, length
    detection: dict        # patterns_matched, leet_speak_conversions, all_caps, ...
    hostility: dict        # score_before, score_after, incident_count, severity_level, should_block
    response: dict         # chosen, template_used, response_time_ms
    action_taken: str      # none | warned_user | blocked_user
    db_incident_id: Optional[int]
    status: str            # success | error


# ---------------------------------------------------------------------------
# Helpers (defined before TranscriptLogger so they are available at class init)
# ---------------------------------------------------------------------------

def _make_session_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"session_{ts}"


def _routing_explanation(routing_type: str) -> str:
    """Return a human-readable explanation for a routing_type label."""
    return {
        "knowledge_base":  "Response came from verified knowledge base",
        "safe_response":   "Response came from pre-written safe responses",
        "creative":        "Response used light creativity grounded in verified facts",
        "hostile_block":   "Message was blocked due to clear hostility",
        "boundary":        "Boundary response applied for mild frustration/sarcasm",
        "default":         "Fallback unclear-question response used",
    }.get(routing_type, "Routing type unknown")


# ---------------------------------------------------------------------------
# Singleton logger
# ---------------------------------------------------------------------------

class TranscriptLogger:
    """Thread-safe singleton that writes JSON transcript entries."""

    _instance: Optional["TranscriptLogger"] = None
    _lock = threading.Lock()

    def __init__(self, session_file: str = SESSION_FILE) -> None:
        self._session_file = session_file
        self._write_lock = threading.Lock()
        self._session_id: str = _make_session_id()
        self._entry_count: int = 0
        self._init_session_file()

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "TranscriptLogger":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        text: str,
        user_key: str,
        platform: str,
        insult_result,           # InsultDetectionResult | None
        hostility_result,        # HostilityResult
        hostility_score_before: int,
        hostility_score_after: int,
        action_taken: str,
        db_incident_id: Optional[int],
        response_template: str,
        via_ollama: bool,
        total_time_ms: float,
        username: str = "",
        score_delta: int = 0,
        incident_count: int = 0,
        intent_category: str = "neutral",
        intent_confidence: float = 0.0,
        intent_explanation: str = "",
        intent_tone_markers: Optional[list] = None,
        recommended_response: str = "no_response",
        routing_type: str = "",
        routing_verified_facts: bool = False,
        routing_safe_response: bool = False,
        routing_creative_allowed: bool = False,
        routing_hallucination_risk: str = "unknown",
    ) -> None:
        """Build and persist a single transcript entry.

        New optional parameters (guardrail system):
            routing_type              — One of: 'knowledge_base', 'safe_response',
                                        'creative', 'hostile_block', 'boundary', 'default'.
            routing_verified_facts    — True when response came from knowledge_base.json.
            routing_safe_response     — True when response came from safe_responses.json.
            routing_creative_allowed  — True when light creativity was permitted.
            routing_hallucination_risk — 'low' | 'none' | 'prevented' | 'unknown'.
        """
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # --- message block ---
            normalized_text = ""
            leet_conversions: list = []
            all_caps = False
            all_caps_ratio = 0.0
            detection_time_ms = 0.0
            patterns_matched: list = []
            via_detector = False

            if insult_result is not None:
                normalized_text = insult_result.normalized_text
                leet_conversions = insult_result.leet_speak_conversions
                all_caps = insult_result.all_caps
                all_caps_ratio = insult_result.all_caps_ratio
                detection_time_ms = insult_result.detection_time_ms
                via_detector = insult_result.detected
                patterns_matched = [
                    {
                        "pattern": m.pattern,
                        "category": m.category,
                        "severity": m.severity,
                        "confidence": m.confidence,
                        "position_in_text": m.position_in_text,
                        "matched_token": m.matched_token,
                    }
                    for m in insult_result.all_matches
                ]

            # Severity level from hostility result
            severity_level = hostility_result.level.value if hasattr(hostility_result.level, "value") else str(hostility_result.level)

            # should_block inferred from action
            should_block = action_taken == "blocked_user"

            entry: dict[str, Any] = {
                "timestamp": ts,
                "session_id": self._session_id,
                "user_id": user_key,
                "username": username,
                "platform": platform,
                "message": {
                    "raw": text,
                    "normalized": normalized_text,
                    "length": len(text),
                },
                "detection": {
                    "patterns_matched": patterns_matched,
                    "leet_speak_conversions": leet_conversions,
                    "all_caps": all_caps,
                    "all_caps_ratio": round(all_caps_ratio, 4),
                    "via_detector": via_detector,
                    "via_ollama": via_ollama,
                    "detection_time_ms": round(detection_time_ms, 3),
                },
                "hostility": {
                    "score_before": hostility_score_before,
                    "score_after": hostility_score_after,
                    "score_delta": score_delta,
                    "severity_level": severity_level,
                    "should_block": should_block,
                    "incident_count": incident_count,
                },
                "response": {
                    "chosen": hostility_result.response,
                    "template_used": response_template,
                    "response_time_ms": round(total_time_ms - detection_time_ms, 3),
                },
                "action_taken": action_taken,
                "db_incident_id": db_incident_id,
                "intent_classification": {
                    "category": intent_category,
                    "confidence": round(intent_confidence, 2),
                    "explanation": intent_explanation,
                    "tone_markers": intent_tone_markers or [],
                    "recommended_response": recommended_response,
                },
                "response_metadata": {
                    "routing_type": routing_type,
                    "source": {
                        "verified_facts":    routing_verified_facts,
                        "safe_response":     routing_safe_response,
                        "creative_allowed":  routing_creative_allowed,
                        "hallucination_risk": routing_hallucination_risk,
                    },
                    "explanation": _routing_explanation(routing_type),
                },
                "status": "success",
            }

            self._append_entry(entry)

        except Exception as exc:
            # Never crash the bot — silently swallow logging errors
            print(f"⚠️ transcript_logger: log() failed: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_session_file(self) -> None:
        """Write the session header to the transcript file."""
        with self._write_lock:
            path = Path(self._session_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            metadata = {
                "_type": "session_metadata",
                "session_id": self._session_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "version": "1.0",
            }
            with open(self._session_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(metadata) + "\n")

    def _append_entry(self, entry: dict) -> None:
        """Append a JSON entry to the session file (one entry per line / JSONL)."""
        with self._write_lock:
            # Rotate if file is too large
            if self._entry_count >= ROTATION_LIMIT:
                self._rotate()

            with open(self._session_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self._entry_count += 1

    def _rotate(self) -> None:
        """Rename the current session file and start a fresh one."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rotated = self._session_file.replace(".json", f"_{ts}.json")
        try:
            os.rename(self._session_file, rotated)
            print(f"📋 transcript_logger: rotated session to {rotated}")
        except OSError:
            pass
        self._session_id = _make_session_id()
        self._entry_count = 0
        self._init_session_file()


def _load_entries(transcript_file: str = SESSION_FILE) -> list[dict]:
    """Load all transcript entries from a JSONL file (skips metadata lines)."""
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


# ---------------------------------------------------------------------------
# CLI Report Generation (delegates to transcript_analyzer)
# ---------------------------------------------------------------------------

def _cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcript logger CLI — generate reports and exports from session transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python transcript_logger.py --report summary
  python transcript_logger.py --report patterns --top 20
  python transcript_logger.py --report user_journey --user "username"
  python transcript_logger.py --export html --output report.html
  python transcript_logger.py --export csv --filter "severity:severe" --output severe_only.csv
""",
    )
    parser.add_argument(
        "--transcript", default=SESSION_FILE,
        help="Path to the JSONL transcript file (default: transcript_current_session.json)"
    )
    parser.add_argument(
        "--report", choices=["summary", "patterns", "user_journey", "severity"],
        help="Generate a report of the given type"
    )
    parser.add_argument("--top", type=int, default=10,
                        help="Top N items to show (used with --report patterns, default: 10)")
    parser.add_argument("--user", default="",
                        help="Filter by user_id (used with --report user_journey)")
    parser.add_argument(
        "--export", choices=["html", "csv", "markdown", "json"],
        help="Export transcript data in the given format"
    )
    parser.add_argument("--output", default="",
                        help="Output file path for --export")
    parser.add_argument(
        "--filter", dest="filter_expr", default="",
        help="Filter expression for --export, e.g. 'severity:severe' or 'user:username'"
    )

    args = parser.parse_args()

    # Import here to avoid circular dependency at module load time
    from transcript_analyzer import TranscriptAnalyzer

    analyzer = TranscriptAnalyzer(args.transcript)

    if args.report:
        if args.report == "summary":
            print(analyzer.summary_report())
        elif args.report == "patterns":
            print(analyzer.patterns_report(top_n=args.top))
        elif args.report == "user_journey":
            print(analyzer.user_journey_report(user_id=args.user))
        elif args.report == "severity":
            print(analyzer.severity_report())
    elif args.export:
        out = args.output or f"transcript_export.{args.export}"
        analyzer.export(args.export, output_path=out, filter_expr=args.filter_expr)
        print(f"✅ Exported to {out}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli_main()
