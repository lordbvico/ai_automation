"""Deploy the Power BI Intelligence Agent to Vertex AI Agent Engine.

Usage
-----
    python deployment/deploy.py --project YOUR_PROJECT --location us-central1

The script wraps the agent in an AdkApp and calls
`vertexai.agent_engines.create()`.  A `deployment_metadata.json` is written
to the project root so subsequent test/update scripts can find the engine.

Prerequisites
-------------
* `gcloud auth application-default login` (or GOOGLE_APPLICATION_CREDENTIALS)
* The deploying identity needs roles/aiplatform.admin on the project.
* Power BI credentials stored in Secret Manager (see README).

Secrets are passed to Agent Engine via the --secrets flag:
    python deployment/deploy.py \\
        --project my-project \\
        --location us-central1 \\
        --secrets AZURE_TENANT_ID=pbi-tenant-id \\
                  AZURE_CLIENT_ID=pbi-client-id \\
                  AZURE_CLIENT_SECRET=pbi-client-secret
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
METADATA_FILE = PROJECT_ROOT / "deployment_metadata.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deploy to Vertex AI Agent Engine")
    p.add_argument("--project", required=True, help="GCP project ID")
    p.add_argument("--location", default="us-central1", help="GCP region")
    p.add_argument(
        "--secrets",
        nargs="*",
        metavar="ENV=SECRET_ID",
        default=[],
        help="Secret Manager mappings: ENV_VAR=secret-id (latest version used)",
    )
    p.add_argument(
        "--display-name",
        default="PowerBI Intelligence Agent",
        help="Display name shown in the Agent Engine console",
    )
    return p.parse_args()


def parse_secrets(raw: list[str]) -> dict[str, str]:
    """Parse 'ENV=secret-id' strings into a dict."""
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            logger.error("Invalid secret format %r — expected ENV=secret-id", item)
            sys.exit(1)
        k, v = item.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def main() -> None:
    args = parse_args()
    secrets = parse_secrets(args.secrets)

    try:
        import vertexai
        from vertexai import agent_engines
        from vertexai.preview.reasoning_engines import AdkApp
    except ImportError:
        logger.error(
            "vertexai SDK not installed. Run: pip install 'google-cloud-aiplatform[adk,reasoningengine]'"
        )
        sys.exit(1)

    # Import root_agent — must be importable from project root.
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.agent import root_agent  # noqa: E402

    logger.info("Initialising Vertex AI (project=%s, location=%s)", args.project, args.location)
    vertexai.init(project=args.project, location=args.location)

    app = AdkApp(agent=root_agent, enable_tracing=True)

    # Build env_vars dict for secrets (Agent Engine injects them as env vars).
    env_vars: dict[str, str] = {
        "GOOGLE_CLOUD_PROJECT": args.project,
        "GOOGLE_CLOUD_LOCATION": args.location,
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
    }

    # Secret Manager refs override plain env vars.
    # Format accepted by Agent Engine: {"ENV_VAR": {"secret": "SECRET_ID"}}
    secret_env: dict[str, dict[str, str]] = {
        k: {"secret": v} for k, v in secrets.items()
    }

    logger.info("Creating Agent Engine reasoning engine …")
    engine = agent_engines.create(
        app,
        display_name=args.display_name,
        requirements=[
            "google-adk>=1.0.0",
            "msal>=1.28.0",
            "requests>=2.32.0",
        ],
        env_vars={**env_vars, **secret_env},  # type: ignore[arg-type]
    )

    engine_id = engine.resource_name
    logger.info("Deployment complete!  Engine resource ID:\n  %s", engine_id)

    metadata = {
        "remote_agent_engine_id": engine_id,
        "project": args.project,
        "location": args.location,
        "display_name": args.display_name,
    }
    METADATA_FILE.write_text(json.dumps(metadata, indent=2))
    logger.info("Metadata written to %s", METADATA_FILE)


if __name__ == "__main__":
    main()
