#!/usr/bin/env python3
"""
Policy Compliance Checker
Analyzes a cloud configuration JSON against a plain-text encryption policy using Claude.

Phase 1 — Structured compliance analysis (adaptive thinking, structured output).
Phase 2 — Per-violation remediation: runnable code + Jira ticket (structured output).
Phase 3 — Renders a Board-of-Directors-ready Markdown report combining all findings.

Usage:
    python policy_checker.py <policy.txt> <config.json> [--output report.md]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel


# ── Pydantic models ───────────────────────────────────────────────────────────

class PolicyFinding(BaseModel):
    requirement_id: str           # e.g. "1.3"
    requirement_title: str
    status: Literal["COMPLIANT", "NON_COMPLIANT", "PARTIAL", "N/A"]
    risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "N/A"]
    affected_resources: list[str]
    evidence: str
    remediation_summary: str      # brief description of the fix needed


class ComplianceAnalysis(BaseModel):
    overall_status: Literal["COMPLIANT", "NON_COMPLIANT", "PARTIAL"]
    executive_summary: str        # 2–4 sentences for board-level readers
    findings: list[PolicyFinding]


class JiraTicket(BaseModel):
    summary: str                  # one-line ticket title
    priority: Literal["Critical", "High", "Medium", "Low"]
    labels: list[str]
    description: str              # full issue description with impact and context
    acceptance_criteria: list[str]


class RemediationPackage(BaseModel):
    code_language: str            # used for Markdown fencing: "python", "hcl", "bash"
    code_label: str               # human label: "Python / boto3", "Terraform HCL", …
    code: str                     # the runnable remediation script or patch
    jira_ticket: JiraTicket


# ── Prompts ───────────────────────────────────────────────────────────────────

_COMPLIANCE_SYSTEM = """\
You are a senior cloud-security auditor. Evaluate the provided cloud configuration
against a written encryption policy and return precise, evidence-based findings.

Rules:
- Produce one finding per numbered policy requirement — no omissions.
- Base every verdict strictly on values present in the configuration JSON.
- Never speculate about capabilities that are not explicitly shown.
- Use "N/A" for requirements that do not apply to the given configuration.
- Populate affected_resources with the specific resource names/IDs from the config."""

_REMEDIATION_SYSTEM = """\
You are a cloud security engineer generating remediation artifacts for a compliance gap.
Write production-quality code that is safe, well-commented, and idempotent.
Include a --dry-run / plan mode or confirmation prompt before any destructive operation."""


def _compliance_user_msg(policy: str, config: str) -> str:
    return f"""\
Analyze the configuration against the policy below.
Return a structured ComplianceAnalysis with a finding for every numbered requirement.

=== ENCRYPTION POLICY ===
{policy}

=== CLOUD CONFIGURATION ===
```json
{config}
```"""


def _remediation_user_msg(finding: PolicyFinding, config: str) -> str:
    resources = ", ".join(finding.affected_resources) or "see evidence"
    return f"""\
A compliance audit identified the following violation. Generate remediation artifacts.

  Requirement : {finding.requirement_id} — {finding.requirement_title}
  Risk Level  : {finding.risk_level}
  Resources   : {resources}
  Evidence    : {finding.evidence}
  Fix needed  : {finding.remediation_summary}

Full cloud configuration for context:
```json
{config}
```

Choose the most appropriate remediation format given the cloud provider and the nature
of the fix (Python/boto3, Terraform HCL, or Bash/CLI). Add error handling and a
dry-run/plan mode where meaningful."""


# ── Core logic ────────────────────────────────────────────────────────────────

def _phase1_analyze(client: anthropic.Anthropic, policy: str, config: str) -> ComplianceAnalysis:
    """Structured compliance analysis with adaptive thinking."""
    print("Phase 1 — Analyzing compliance...", file=sys.stderr)

    response = client.messages.parse(
        model="claude-opus-4-6",
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=_COMPLIANCE_SYSTEM,
        messages=[{"role": "user", "content": _compliance_user_msg(policy, config)}],
        output_format=ComplianceAnalysis,
    )

    result = response.parsed_output
    if result is None:
        sys.exit("Error: compliance analysis returned no structured output.")

    violations = sum(1 for f in result.findings if f.status in ("NON_COMPLIANT", "PARTIAL"))
    print(
        f"         Done — {len(result.findings)} requirements checked, "
        f"{violations} violation(s) found.\n",
        file=sys.stderr,
    )
    return result


def _phase2_remediate(
    client: anthropic.Anthropic,
    finding: PolicyFinding,
    config: str,
) -> RemediationPackage:
    """Generate remediation code + Jira ticket for a single violation."""
    print(
        f"  [{finding.risk_level}] {finding.requirement_id} — {finding.requirement_title}",
        file=sys.stderr,
    )

    response = client.messages.parse(
        model="claude-opus-4-6",
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=_REMEDIATION_SYSTEM,
        messages=[{"role": "user", "content": _remediation_user_msg(finding, config)}],
        output_format=RemediationPackage,
    )

    result = response.parsed_output
    if result is None:
        sys.exit(f"Error: remediation generation returned no output for {finding.requirement_id}.")
    return result


# ── Report rendering ──────────────────────────────────────────────────────────

_RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "N/A": 4}
_STATUS_EMOJI = {
    "COMPLIANT": "✅",
    "NON_COMPLIANT": "❌",
    "PARTIAL": "⚠️",
    "N/A": "—",
}


def _render_report(
    analysis: ComplianceAnalysis,
    remediation_map: dict[str, RemediationPackage],
) -> str:
    lines: list[str] = []

    # ── Title ──────────────────────────────────────────────────────────────────
    lines += [
        "# Cloud Encryption Compliance Report",
        "",
    ]

    # ── Executive Summary ──────────────────────────────────────────────────────
    status_label = analysis.overall_status.replace("_", "-")
    lines += [
        "## Executive Summary",
        "",
        f"**Overall Status: {status_label}**",
        "",
        analysis.executive_summary,
        "",
    ]

    # ── Compliance Scorecard ───────────────────────────────────────────────────
    lines += [
        "## Compliance Scorecard",
        "",
        "| # | Requirement | Status | Risk |",
        "|---|-------------|--------|------|",
    ]
    for f in analysis.findings:
        emoji = _STATUS_EMOJI.get(f.status, "")
        risk = f.risk_level if f.status in ("NON_COMPLIANT", "PARTIAL") else "—"
        lines.append(
            f"| {f.requirement_id} | {f.requirement_title} "
            f"| {emoji} {f.status.replace('_', '-')} | {risk} |"
        )
    lines.append("")

    # ── Detailed Findings ──────────────────────────────────────────────────────
    lines += ["## Detailed Findings", ""]

    for f in analysis.findings:
        emoji = _STATUS_EMOJI.get(f.status, "")
        lines += [
            f"### {f.requirement_id} — {f.requirement_title}",
            "",
            f"**Status:** {emoji} {f.status.replace('_', '-')}  ",
            f"**Risk Level:** {f.risk_level}",
            "",
            "**Evidence from Configuration:**",
            "",
            f"> {f.evidence}",
            "",
        ]

        pkg = remediation_map.get(f.requirement_id)
        if pkg:
            # ── Remediation code ───────────────────────────────────────────────
            lines += [
                f"**Remediation Code ({pkg.code_label}):**",
                "",
                f"```{pkg.code_language}",
                pkg.code,
                "```",
                "",
            ]

            # ── Jira ticket ────────────────────────────────────────────────────
            t = pkg.jira_ticket
            labels_str = ", ".join(f"`{lb}`" for lb in t.labels)
            criteria_md = "\n".join(f"- [ ] {c}" for c in t.acceptance_criteria)
            lines += [
                "**Jira Ticket:**",
                "",
                f"> **Summary:** {t.summary}  ",
                f"> **Priority:** {t.priority}  ",
                f"> **Labels:** {labels_str}  ",
                ">",
                "> **Description:**",
                ">",
            ]
            for desc_line in t.description.splitlines():
                lines.append(f"> {desc_line}")
            lines += [
                ">",
                "> **Acceptance Criteria:**",
                ">",
            ]
            for c in t.acceptance_criteria:
                lines.append(f"> - [ ] {c}")
            lines.append("")
        elif f.status == "COMPLIANT":
            lines += [
                "*No remediation required.*",
                "",
            ]
        else:
            lines += [
                f"**Remediation:** {f.remediation_summary}",
                "",
            ]

        lines.append("---")
        lines.append("")

    # ── Risk Summary ───────────────────────────────────────────────────────────
    violations = [
        f for f in analysis.findings if f.status in ("NON_COMPLIANT", "PARTIAL")
    ]
    violations.sort(key=lambda f: _RISK_ORDER.get(f.risk_level, 99))

    lines += ["## Risk Summary", ""]
    if violations:
        critical_high = [v for v in violations if v.risk_level in ("CRITICAL", "HIGH")]
        if critical_high:
            items = "; ".join(
                f"**{v.requirement_id}** ({v.requirement_title})" for v in critical_high
            )
            lines.append(
                f"There are **{len(critical_high)} critical/high-risk** finding(s) "
                f"requiring immediate attention: {items}. "
            )
        lines.append(
            f"In total, **{len(violations)} of {len(analysis.findings)}** requirements "
            "are non-compliant or partially compliant. "
            "These gaps expose the organisation to data-breach risk, regulatory penalties, "
            "and reputational damage."
        )
    else:
        lines.append(
            "All policy requirements are satisfied. "
            "No outstanding encryption risks were identified."
        )
    lines.append("")

    # ── Prioritised Recommendations ────────────────────────────────────────────
    lines += ["## Prioritised Recommendations", ""]
    if violations:
        for i, v in enumerate(violations, 1):
            pkg = remediation_map.get(v.requirement_id)
            ticket_ref = f" *(see Jira ticket: {pkg.jira_ticket.summary})*" if pkg else ""
            lines.append(
                f"{i}. **[{v.risk_level}]** {v.requirement_id} — {v.requirement_title}: "
                f"{v.remediation_summary}{ticket_ref}"
            )
        lines.append("")
    else:
        lines.append("No remediation actions required.\n")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def load_policy(path: str) -> str:
    p = Path(path)
    if not p.exists():
        sys.exit(f"Error: policy file not found: {path}")
    return p.read_text(encoding="utf-8").strip()


def load_config(path: str) -> str:
    p = Path(path)
    if not p.exists():
        sys.exit(f"Error: config file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return json.dumps(data, indent=2)
    except json.JSONDecodeError as exc:
        sys.exit(f"Error: invalid JSON in config file: {exc}")


def run(policy_path: str, config_path: str, output_path: str | None) -> None:
    policy = load_policy(policy_path)
    config = load_config(config_path)
    client = anthropic.Anthropic()

    # Phase 1: structured compliance analysis
    analysis = _phase1_analyze(client, policy, config)

    # Phase 2: generate remediation for every non-compliant / partial finding
    actionable = [
        f for f in analysis.findings if f.status in ("NON_COMPLIANT", "PARTIAL")
    ]
    remediation_map: dict[str, RemediationPackage] = {}

    if actionable:
        print(
            f"Phase 2 — Generating remediation code + Jira tickets "
            f"for {len(actionable)} violation(s)...",
            file=sys.stderr,
        )
        for finding in actionable:
            remediation_map[finding.requirement_id] = _phase2_remediate(
                client, finding, config
            )
        print("         Done.\n", file=sys.stderr)

    # Phase 3: render final report
    report = _render_report(analysis, remediation_map)
    print(report)

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        print(f"Report saved to: {output_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check cloud config compliance against an encryption policy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python policy_checker.py examples/encryption_policy.txt examples/cloud_config.json
  python policy_checker.py policy.txt config.json --output board_report.md""",
    )
    parser.add_argument("policy", help="Path to the encryption policy (.txt)")
    parser.add_argument("config", help="Path to the cloud configuration (.json)")
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write the Markdown report to FILE (also prints to stdout)",
    )

    args = parser.parse_args()
    run(args.policy, args.config, args.output)


if __name__ == "__main__":
    main()
