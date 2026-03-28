"""
transcript_analyzer.py — Analysis and report generation for transcript logs.

Reads JSONL transcript files produced by transcript_logger.py and generates:
  - Summary reports
  - Pattern analysis
  - User journey analysis
  - Severity calibration reports
  - HTML / CSV / Markdown / JSON exports
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from transcript_logger import _load_entries, SESSION_FILE


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class TranscriptAnalyzer:
    """Load transcript entries and produce reports / exports."""

    def __init__(self, transcript_file: str = SESSION_FILE) -> None:
        self._file = transcript_file
        self._entries: list[dict] = _load_entries(transcript_file)

    def reload(self) -> None:
        """Re-read the transcript file."""
        self._entries = _load_entries(self._file)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self, entries: list[dict], filter_expr: str) -> list[dict]:
        """
        Apply a simple 'key:value' filter expression.
        Supported keys: severity, user, action, platform
        """
        if not filter_expr:
            return entries
        parts = filter_expr.split(":", 1)
        if len(parts) != 2:
            return entries
        key, value = parts[0].strip().lower(), parts[1].strip().lower()
        result = []
        for e in entries:
            if key == "severity":
                if e.get("hostility", {}).get("severity_level", "").lower() == value:
                    result.append(e)
            elif key == "user":
                if e.get("user_id", "").lower() == value:
                    result.append(e)
            elif key == "action":
                if e.get("action_taken", "").lower() == value:
                    result.append(e)
            elif key == "platform":
                if e.get("platform", "").lower() == value:
                    result.append(e)
        return result

    # ------------------------------------------------------------------
    # Summary report
    # ------------------------------------------------------------------

    def summary_report(self) -> str:
        entries = self._entries
        total = len(entries)
        if total == 0:
            return "No transcript entries found."

        detected = sum(1 for e in entries if e.get("detection", {}).get("via_detector") or
                       any(e.get("detection", {}).get("patterns_matched", [])))
        via_ollama = sum(1 for e in entries if e.get("detection", {}).get("via_ollama"))
        blocked = sum(1 for e in entries if e.get("action_taken") == "blocked_user")
        warned = sum(1 for e in entries if e.get("action_taken") == "warned_user")

        severity_counter: Counter = Counter()
        scores_after: list[int] = []
        for e in entries:
            h = e.get("hostility", {})
            sev = h.get("severity_level", "none")
            severity_counter[sev] += 1
            score = h.get("score_after", 0)
            if score:
                scores_after.append(score)

        avg_score = round(sum(scores_after) / len(scores_after), 2) if scores_after else 0.0
        detection_rate = round(detected / total * 100, 1) if total else 0
        blocking_rate = round(blocked / total * 100, 1) if total else 0

        lines = [
            "=" * 60,
            "  TRANSCRIPT SUMMARY REPORT",
            "=" * 60,
            f"  Transcript file   : {self._file}",
            f"  Total entries     : {total}",
            f"  Detection rate    : {detection_rate}% ({detected}/{total})",
            f"  Via detector      : {detected}",
            f"  Via Ollama        : {via_ollama}",
            f"  Avg hostility score: {avg_score}",
            f"  Blocking rate     : {blocking_rate}% ({blocked}/{total})",
            f"  Warnings issued   : {warned}",
            "",
            "  Severity breakdown:",
        ]
        for sev in ("none", "mild", "moderate", "severe", "threat"):
            count = severity_counter.get(sev, 0)
            pct = round(count / total * 100, 1) if total else 0
            lines.append(f"    {sev:<10}: {count:>5}  ({pct}%)")
        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Pattern report
    # ------------------------------------------------------------------

    def patterns_report(self, top_n: int = 10) -> str:
        entries = self._entries
        if not entries:
            return "No transcript entries found."

        pattern_counter: Counter = Counter()
        category_counter: Counter = Counter()
        confidence_totals: dict[str, list[float]] = defaultdict(list)
        cooccurrence: Counter = Counter()

        for e in entries:
            matches = e.get("detection", {}).get("patterns_matched", [])
            phrases = [m.get("pattern", "") for m in matches]
            for m in matches:
                pat = m.get("pattern", "")
                cat = m.get("category", "")
                conf = m.get("confidence", 0.0)
                if pat:
                    pattern_counter[pat] += 1
                    confidence_totals[pat].append(conf)
                if cat:
                    category_counter[cat] += 1
            # Co-occurrence: pairs of patterns in same message
            for i, p1 in enumerate(phrases):
                for p2 in phrases[i + 1:]:
                    pair = tuple(sorted([p1, p2]))
                    cooccurrence[pair] += 1

        lines = [
            "=" * 60,
            "  PATTERN ANALYSIS REPORT",
            "=" * 60,
            f"  Top {top_n} most matched patterns:",
        ]
        for pat, count in pattern_counter.most_common(top_n):
            avg_conf = round(sum(confidence_totals[pat]) / len(confidence_totals[pat]), 3)
            lines.append(f"    {pat:<40} {count:>5} hits  avg_conf={avg_conf}")

        lines += ["", f"  Top {top_n} highest-confidence patterns:"]
        sorted_by_conf = sorted(
            confidence_totals.items(),
            key=lambda kv: sum(kv[1]) / len(kv[1]) if kv[1] else 0,
            reverse=True,
        )[:top_n]
        for pat, confs in sorted_by_conf:
            avg_conf = round(sum(confs) / len(confs), 3)
            lines.append(f"    {pat:<40} avg_conf={avg_conf}  ({len(confs)} hits)")

        lines += ["", "  Category breakdown:"]
        for cat, count in category_counter.most_common():
            lines.append(f"    {cat:<45} {count:>5}")

        if cooccurrence:
            lines += ["", f"  Top {top_n} co-occurring pattern pairs:"]
            for (p1, p2), count in cooccurrence.most_common(top_n):
                lines.append(f"    '{p1}' + '{p2}'  →  {count} times")

        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # User journey report
    # ------------------------------------------------------------------

    def user_journey_report(self, user_id: str = "") -> str:
        entries = self._entries
        if not entries:
            return "No transcript entries found."

        if user_id:
            user_entries = [e for e in entries if e.get("user_id", "").lower() == user_id.lower()]
        else:
            # Show all users with at least one hostile interaction
            hostile_users: set = set()
            for e in entries:
                if e.get("action_taken") in ("warned_user", "blocked_user"):
                    hostile_users.add(e.get("user_id", ""))
            user_entries = [e for e in entries if e.get("user_id", "") in hostile_users]

        if not user_entries:
            return f"No entries found for user '{user_id}'." if user_id else "No hostile user journeys found."

        # Group by user
        by_user: dict[str, list[dict]] = defaultdict(list)
        for e in user_entries:
            by_user[e.get("user_id", "unknown")].append(e)

        lines = [
            "=" * 60,
            "  USER JOURNEY REPORT",
            "=" * 60,
        ]
        for uid, msgs in sorted(by_user.items()):
            lines += [f"\n  User: {uid}  ({len(msgs)} messages)"]
            prev_ts = None
            for i, e in enumerate(msgs, 1):
                ts = e.get("timestamp", "")
                raw = e.get("message", {}).get("raw", "")[:60]
                sev = e.get("hostility", {}).get("severity_level", "none")
                score = e.get("hostility", {}).get("score_after", 0)
                action = e.get("action_taken", "none")
                gap = ""
                if prev_ts and ts:
                    try:
                        t1 = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        t0 = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                        delta = (t1 - t0).total_seconds()
                        gap = f"  (+{delta:.0f}s)"
                    except ValueError:
                        pass
                lines.append(f"    [{i:>3}] {ts}{gap}")
                lines.append(f"          msg: {raw!r}")
                lines.append(f"          sev={sev}  score={score}  action={action}")
                prev_ts = ts
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Severity calibration report
    # ------------------------------------------------------------------

    def severity_report(self) -> str:
        entries = self._entries
        if not entries:
            return "No transcript entries found."

        sev_groups: dict[str, list[dict]] = defaultdict(list)
        for e in entries:
            sev = e.get("hostility", {}).get("severity_level", "none")
            sev_groups[sev].append(e)

        total = len(entries)
        lines = [
            "=" * 60,
            "  SEVERITY CALIBRATION REPORT",
            "=" * 60,
            f"  Total messages: {total}",
        ]
        for sev in ("none", "mild", "moderate", "severe", "threat"):
            group = sev_groups.get(sev, [])
            count = len(group)
            pct = round(count / total * 100, 1) if total else 0
            blocked = sum(1 for e in group if e.get("action_taken") == "blocked_user")
            warned = sum(1 for e in group if e.get("action_taken") == "warned_user")
            # Avg confidence for this severity
            confs: list[float] = []
            for e in group:
                for m in e.get("detection", {}).get("patterns_matched", []):
                    if m.get("severity", "").lower() == sev:
                        confs.append(m.get("confidence", 0.0))
            avg_conf = round(sum(confs) / len(confs), 3) if confs else 0.0
            lines += [
                f"\n  {sev.upper()} ({count} — {pct}%)",
                f"    Blocked  : {blocked}",
                f"    Warned   : {warned}",
                f"    Avg conf : {avg_conf}",
            ]
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(
        self,
        fmt: str,
        output_path: str = "",
        filter_expr: str = "",
    ) -> str:
        """Export transcript data. Returns the output path used."""
        entries = self._apply_filter(self._entries, filter_expr)
        fmt = fmt.lower()
        if fmt == "json":
            content = self._export_json(entries)
            ext = "json"
        elif fmt == "csv":
            content = self._export_csv(entries)
            ext = "csv"
        elif fmt == "markdown":
            content = self._export_markdown(entries)
            ext = "md"
        elif fmt == "html":
            content = self._export_html(entries)
            ext = "html"
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        out = output_path or f"transcript_export.{ext}"
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        return out

    # --- JSON export -------------------------------------------------------

    def _export_json(self, entries: list[dict]) -> str:
        return json.dumps(entries, indent=2, ensure_ascii=False)

    # --- CSV export --------------------------------------------------------

    def _export_csv(self, entries: list[dict]) -> str:
        buf = io.StringIO()
        fieldnames = [
            "timestamp", "session_id", "user_id", "platform",
            "message_raw", "message_normalized", "message_length",
            "severity_level", "action_taken", "hostility_score_before",
            "hostility_score_after", "via_detector", "via_ollama",
            "patterns_matched_count", "detection_time_ms",
            "response_chosen", "response_template",
            "db_incident_id", "status",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            msg = e.get("message", {})
            det = e.get("detection", {})
            hos = e.get("hostility", {})
            resp = e.get("response", {})
            writer.writerow({
                "timestamp": e.get("timestamp", ""),
                "session_id": e.get("session_id", ""),
                "user_id": e.get("user_id", ""),
                "platform": e.get("platform", ""),
                "message_raw": msg.get("raw", ""),
                "message_normalized": msg.get("normalized", ""),
                "message_length": msg.get("length", 0),
                "severity_level": hos.get("severity_level", "none"),
                "action_taken": e.get("action_taken", "none"),
                "hostility_score_before": hos.get("score_before", 0),
                "hostility_score_after": hos.get("score_after", 0),
                "via_detector": det.get("via_detector", False),
                "via_ollama": det.get("via_ollama", False),
                "patterns_matched_count": len(det.get("patterns_matched", [])),
                "detection_time_ms": det.get("detection_time_ms", 0),
                "response_chosen": resp.get("chosen", ""),
                "response_template": resp.get("template_used", ""),
                "db_incident_id": e.get("db_incident_id", ""),
                "status": e.get("status", ""),
            })
        return buf.getvalue()

    # --- Markdown export ---------------------------------------------------

    def _export_markdown(self, entries: list[dict]) -> str:
        lines = [
            "# Transcript Report",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Total entries: {len(entries)}",
            "",
            "---",
            "",
        ]
        for i, e in enumerate(entries, 1):
            msg = e.get("message", {})
            det = e.get("detection", {})
            hos = e.get("hostility", {})
            resp = e.get("response", {})
            lines += [
                f"## Entry {i} — {e.get('timestamp', '')}",
                "",
                f"**User:** `{e.get('user_id', '')}` | **Platform:** {e.get('platform', '')}",
                f"**Action:** {e.get('action_taken', 'none')} | **Status:** {e.get('status', '')}",
                "",
                f"**Message (raw):** {msg.get('raw', '')}",
                f"**Normalized:** {msg.get('normalized', '')}",
                "",
                f"**Severity:** {hos.get('severity_level', 'none')} | "
                f"**Score:** {hos.get('score_before', 0)} → {hos.get('score_after', 0)}",
            ]
            patterns = det.get("patterns_matched", [])
            if patterns:
                lines += ["", "**Patterns matched:**"]
                for m in patterns:
                    lines.append(
                        f"- `{m.get('pattern', '')}` ({m.get('category', '')} / "
                        f"{m.get('severity', '')} / conf={m.get('confidence', 0)})"
                    )
            if resp.get("chosen"):
                lines += ["", f"**Bot response:** {resp['chosen']}"]
            lines += ["", "---", ""]
        return "\n".join(lines)

    # --- HTML export -------------------------------------------------------

    def _export_html(self, entries: list[dict]) -> str:
        sev_colors = {
            "none": "#e8f5e9",
            "mild": "#fff9c4",
            "moderate": "#ffe0b2",
            "severe": "#ffcdd2",
            "threat": "#b71c1c",
        }

        rows = []
        for e in entries:
            msg = e.get("message", {})
            det = e.get("detection", {})
            hos = e.get("hostility", {})
            resp = e.get("response", {})
            sev = hos.get("severity_level", "none")
            color = sev_colors.get(sev, "#ffffff")
            patterns_html = ""
            for m in det.get("patterns_matched", []):
                patterns_html += (
                    f'<span class="badge">{_h(m.get("pattern",""))} '
                    f'<small>[{_h(m.get("severity",""))} conf={m.get("confidence",0)}]</small></span> '
                )

            rows.append(
                f"""<tr style="background:{color}">
                  <td>{_h(e.get("timestamp",""))}</td>
                  <td>{_h(e.get("user_id",""))}</td>
                  <td>{_h(e.get("platform",""))}</td>
                  <td>{_h(msg.get("raw",""))}</td>
                  <td>{_h(sev)}</td>
                  <td>{hos.get("score_before",0)} → {hos.get("score_after",0)}</td>
                  <td>{patterns_html}</td>
                  <td>{_h(e.get("action_taken","none"))}</td>
                  <td>{_h(resp.get("chosen",""))[:80]}</td>
                </tr>"""
            )

        rows_html = "\n".join(rows)
        total = len(entries)
        blocked = sum(1 for e in entries if e.get("action_taken") == "blocked_user")
        warned = sum(1 for e in entries if e.get("action_taken") == "warned_user")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Quiet Reach — Transcript Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; color: #212121; }}
    h1 {{ color: #1a237e; }}
    .stats {{ display: flex; gap: 2rem; margin: 1rem 0 2rem; flex-wrap: wrap; }}
    .stat-card {{ background: #fff; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
    .stat-card .num {{ font-size: 2rem; font-weight: bold; color: #3949ab; }}
    .stat-card .lbl {{ font-size: .85rem; color: #757575; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
    th {{ background: #3949ab; color: #fff; padding: .6rem 1rem; text-align: left; font-size: .85rem; }}
    td {{ padding: .5rem 1rem; border-bottom: 1px solid #e0e0e0; font-size: .85rem; vertical-align: top; }}
    .badge {{ display: inline-block; background: #e8eaf6; border-radius: 4px; padding: .1rem .4rem;
              margin: .1rem; font-size: .75rem; }}
    footer {{ margin-top: 2rem; font-size: .8rem; color: #9e9e9e; }}
  </style>
</head>
<body>
  <h1>🎯 Quiet Reach — Transcript Report</h1>
  <p>Generated: {datetime.now(timezone.utc).isoformat()} &nbsp;|&nbsp; File: {_h(self._file)}</p>

  <div class="stats">
    <div class="stat-card"><div class="num">{total}</div><div class="lbl">Total messages</div></div>
    <div class="stat-card"><div class="num">{warned}</div><div class="lbl">Warnings issued</div></div>
    <div class="stat-card"><div class="num">{blocked}</div><div class="lbl">Users blocked</div></div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Timestamp</th>
        <th>User</th>
        <th>Platform</th>
        <th>Message</th>
        <th>Severity</th>
        <th>Score</th>
        <th>Patterns</th>
        <th>Action</th>
        <th>Response</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  <footer>Quiet Reach Transcript Logger v1.0</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTML escaping helper
# ---------------------------------------------------------------------------

def _h(s: Any) -> str:
    """Minimal HTML escaping."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
