# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Tool Does

`policy_checker.py` takes a plain-text encryption policy and a cloud-configuration JSON file,
runs a two-phase Claude analysis, and produces a Board-of-Directors-ready Markdown compliance
report that includes runnable remediation code and Jira tickets for every violation.

## Running the Tool

```bash
# Install dependencies (one-time)
pip install -r requirements.txt

# Run against the bundled examples
python policy_checker.py examples/encryption_policy.txt examples/cloud_config.json

# Save the report to a file
python policy_checker.py policy.txt config.json --output board_report.md
```

`ANTHROPIC_API_KEY` must be set in the environment.

## Architecture

Everything lives in `policy_checker.py`. The tool runs in three phases:

### Phase 1 — Structured compliance analysis

`_phase1_analyze()` calls `client.messages.parse()` with `thinking: {"type": "adaptive"}` and
a Pydantic `ComplianceAnalysis` output format. Claude reasons through every numbered policy
requirement and returns one `PolicyFinding` per requirement — including status, risk level,
affected resources, evidence, and a brief remediation summary.

### Phase 2 — Per-violation remediation generation

`_phase2_remediate()` is called once per `NON_COMPLIANT` or `PARTIAL` finding. It calls
`client.messages.parse()` with a `RemediationPackage` output format, asking Claude to produce:
- **Runnable remediation code** — Python/boto3, Terraform HCL, or Bash/CLI chosen by Claude
  based on the cloud provider and nature of the fix. Includes dry-run/plan mode.
- **A Jira ticket** — summary, priority, labels, full description, and acceptance criteria.

### Phase 3 — Report rendering

`_render_report()` combines the `ComplianceAnalysis` and the `remediation_map` into a single
Markdown document with Executive Summary, Compliance Scorecard, Detailed Findings (one section
per requirement, with embedded code blocks and Jira ticket), Risk Summary, and Prioritised
Recommendations sorted by risk severity.

## Pydantic Models

| Model | Purpose |
|---|---|
| `PolicyFinding` | One compliance finding per policy requirement |
| `ComplianceAnalysis` | Full Phase 1 output — overall status + list of findings |
| `JiraTicket` | Summary, priority, labels, description, acceptance criteria |
| `RemediationPackage` | Remediation code (language + content) + `JiraTicket` |

## Sample Files

| File | Purpose |
|---|---|
| `examples/encryption_policy.txt` | Five-section policy covering storage, transit, key management, certificates, and databases |
| `examples/cloud_config.json` | AWS config with intentional gaps (unencrypted S3 bucket, unencrypted legacy EBS volume, publicly-accessible dev DB, disabled key rotation) for realistic demo output |
