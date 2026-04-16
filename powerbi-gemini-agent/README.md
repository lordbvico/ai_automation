# Power BI Intelligence Agent

A conversational AI agent built with **Google ADK** and deployed to **Vertex AI Agent Engine**. It connects to Microsoft Power BI via the Power BI REST API and answers natural-language questions about workspaces, reports, dashboards, and datasets using **Gemini Enterprise** (Gemini on Vertex AI).

## Architecture

```
User ──► Vertex AI Agent Engine
              │
              ▼
     gemini-3-flash-preview (Gemini Enterprise)
              │
        ADK tool calls
              │
     ┌────────┴────────┐
     │  Power BI REST  │
     │      API        │
     │  (Azure AD      │
     │   OAuth2)       │
     └─────────────────┘
```

## Capabilities

| User question | Tools invoked |
|---|---|
| "What workspaces do I have?" | `list_workspaces` |
| "Show me reports in Finance workspace" | `list_workspaces` → `list_reports` |
| "Summarise the Sales KPI dashboard" | `list_workspaces` → `list_dashboards` → `get_dashboard_tiles` |
| "Total sales by region last quarter" | `list_workspaces` → `list_datasets` → `execute_dax_query` |
| "What data sources does the Sales dataset use?" | `get_dataset_datasources` |

## Project structure

```
powerbi-gemini-agent/
├── app/
│   ├── agent.py          ← Root ADK agent (root_agent)
│   └── tools/
│       ├── auth.py       ← MSAL Azure AD token management
│       └── powerbi.py    ← Power BI REST API tool functions
├── deployment/
│   └── deploy.py         ← Vertex AI Agent Engine deployment script
├── tests/
│   ├── eval/             ← ADK eval config + evalsets
│   └── unit/             ← pytest unit tests (no live credentials needed)
├── .env.example          ← Required environment variables
├── pyproject.toml
└── DESIGN_SPEC.md
```

## Setup

### 1. Prerequisites

- Python 3.10+
- A GCP project with Vertex AI API enabled
- `gcloud auth application-default login`
- A Power BI service principal (App Registration in Azure AD) with:
  - Power BI **Workspace Member** role (or Admin) on target workspaces
  - Azure AD API permission: `PowerBI Service → Tenant.Read.All` (application)

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your GCP project, Azure tenant, client ID, and client secret
```

### 4. Local development

```bash
# Interactive web UI (hot-reload)
adk web .

# CLI chat
adk run app/

# Run unit tests
pytest tests/unit/

# Run evaluations (requires live credentials)
adk eval app/ tests/eval/evalsets/powerbi_eval.evalset.json \
    --eval_config tests/eval/eval_config.json
```

## Deployment to Vertex AI Agent Engine

Store credentials in GCP Secret Manager first:

```bash
echo -n "$AZURE_TENANT_ID"     | gcloud secrets create pbi-tenant-id     --data-file=-
echo -n "$AZURE_CLIENT_ID"     | gcloud secrets create pbi-client-id      --data-file=-
echo -n "$AZURE_CLIENT_SECRET" | gcloud secrets create pbi-client-secret  --data-file=-
```

Grant the Agent Engine service account access:

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

for secret in pbi-tenant-id pbi-client-id pbi-client-secret; do
  gcloud secrets add-iam-policy-binding $secret \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

Deploy:

```bash
python deployment/deploy.py \
  --project YOUR_PROJECT_ID \
  --location us-central1 \
  --secrets AZURE_TENANT_ID=pbi-tenant-id \
            AZURE_CLIENT_ID=pbi-client-id \
            AZURE_CLIENT_SECRET=pbi-client-secret
```

This writes `deployment_metadata.json` with the engine resource ID.

### Test the deployed agent

```python
import json, vertexai

metadata = json.load(open("deployment_metadata.json"))
vertexai.init(project=metadata["project"], location=metadata["location"])

client = vertexai.Client(location=metadata["location"])
agent  = client.agent_engines.get(name=metadata["remote_agent_engine_id"])

async for event in agent.async_stream_query(
    message="What workspaces do I have access to?",
    user_id="test-user",
):
    print(event)
```

## Gemini Enterprise

By setting `GOOGLE_GENAI_USE_VERTEXAI=true`, all Gemini API calls are routed through
**Vertex AI** — giving you:

- Enterprise data governance (prompts/responses are not used for model training)
- VPC Service Controls support
- Cloud Audit Logs for all AI API calls
- SLA-backed availability

The agent uses `gemini-3-flash-preview` by default. Change the `model` parameter in
[`app/agent.py`](app/agent.py) to switch to `gemini-3-pro-preview` for more complex
analytical tasks.
