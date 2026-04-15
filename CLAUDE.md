# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Tool Does

`policy_checker.py` takes a plain-text encryption policy and a cloud-configuration JSON file, sends both to Claude (claude-opus-4-6 with adaptive thinking), and streams a Board-of-Directors-ready Markdown compliance report to stdout.

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

Everything lives in one file — `policy_checker.py`:

- **`SYSTEM_PROMPT`** — sets Claude's persona as a senior security auditor.
- **`REPORT_PROMPT`** — injected as the user message; contains the policy text and config JSON verbatim, then prescribes the exact Markdown sections Claude must produce (Executive Summary, Scorecard, Detailed Findings, Risk Summary, Recommendations).
- **`run()`** — streams the response from `client.messages.stream()` using `thinking: {"type": "adaptive"}`. Thinking blocks are acknowledged to stderr; only `text_delta` events are collected and printed to stdout.
- **`load_policy()` / `load_config()`** — read and validate the two input files. `load_config` normalises to pretty-printed JSON so the token count is predictable.

## Key Design Choices

- **Adaptive thinking** is enabled so Claude reasons through ambiguous policy language before writing findings. This is the primary lever for report quality.
- **Streaming** is used because the report can be several thousand tokens; streaming prevents HTTP timeouts and gives the user immediate feedback.
- **Output goes to stdout** so it can be piped. `--output` is additive (also prints to stdout).
- **Stderr for diagnostics** — "Reasoning..." and "done." messages go to stderr so they don't pollute the Markdown when the output is piped or redirected.

## Sample Files

| File | Purpose |
|---|---|
| `examples/encryption_policy.txt` | Five-section policy covering storage, transit, key management, certificates, and databases |
| `examples/cloud_config.json` | AWS config with intentional gaps (unencrypted S3 bucket, unencrypted EBS volume, publicly-accessible DB) for realistic demo output |
