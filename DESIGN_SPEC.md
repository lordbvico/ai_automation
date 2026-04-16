# DESIGN_SPEC.md — Power BI Intelligence Agent

## Overview

This agent connects to Microsoft Power BI via the Power BI REST API and exposes an
AI-powered conversational interface powered by Gemini Enterprise (Gemini models on
Vertex AI). Users can ask natural-language questions about their Power BI workspaces,
reports, dashboards, and datasets. The agent translates those questions into the
appropriate API calls or DAX queries, fetches the data, and returns clear, analytical
summaries with supporting figures.

The agent authenticates to Power BI using Azure Active Directory service-principal
credentials (client-credentials flow), which is the recommended approach for unattended
server-side access. All credentials are stored in GCP Secret Manager and never appear
in code or environment files. The agent is deployed to Vertex AI Agent Engine so that
sessions are fully managed by Google Cloud and enterprise data never leaves the VPC.

The system is designed for BI analysts, data engineers, and executives who want to
query Power BI data conversationally without writing DAX or navigating the Power BI UI.

## Example Use Cases

1. **Workspace overview**
   - Input: "What workspaces do I have access to and what reports are in each?"
   - Output: Formatted list of workspaces with their reports, owners, and last-refresh
     timestamps.

2. **Dashboard summary**
   - Input: "Give me a summary of the Sales KPI dashboard in the Finance workspace."
   - Output: Tile-by-tile breakdown of each KPI tile (name, value, target), formatted
     as a markdown table.

3. **Ad-hoc DAX query**
   - Input: "What were total sales by region for Q1 2024 from the Sales dataset?"
   - Output: DAX query constructed and executed via Power BI REST API; results returned
     as a markdown table with a brief narrative summary.

4. **Dataset discovery**
   - Input: "Show me all datasets in the Marketing workspace and their refresh schedules."
   - Output: Table of datasets with schema summary, owner, and last-refresh time.

5. **Report page inspection**
   - Input: "List the pages of the Quarterly Review report and describe what each covers."
   - Output: Page-by-page listing with display names and order.

## Tools Required

| Tool | Purpose | API / Auth |
|---|---|---|
| `list_workspaces` | List all Power BI workspaces the service principal has access to | `GET /v1.0/myorg/groups` — Bearer token from Azure AD |
| `list_reports` | List reports inside a given workspace | `GET /v1.0/myorg/groups/{groupId}/reports` |
| `list_dashboards` | List dashboards inside a given workspace | `GET /v1.0/myorg/groups/{groupId}/dashboards` |
| `get_dashboard_tiles` | Retrieve all tiles in a dashboard with their values | `GET /v1.0/myorg/groups/{groupId}/dashboards/{dashboardId}/tiles` |
| `list_datasets` | List datasets in a workspace | `GET /v1.0/myorg/groups/{groupId}/datasets` |
| `get_dataset_tables` | Get tables and columns for a dataset | `GET /v1.0/myorg/groups/{groupId}/datasets/{datasetId}/datasources` + schema |
| `execute_dax_query` | Run a DAX query against a dataset and return rows | `POST /v1.0/myorg/groups/{groupId}/datasets/{datasetId}/executeQueries` |
| `list_report_pages` | List pages of a report | `GET /v1.0/myorg/groups/{groupId}/reports/{reportId}/pages` |

**Authentication:** `msal.ConfidentialClientApplication` with client-credentials flow.
Credentials (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`) are read from
environment variables (injected from GCP Secret Manager at deploy time).

## Constraints & Safety Rules

- **Read-only**: The agent MUST NOT create, update, or delete any Power BI resource.
  It may only call GET endpoints and the executeQueries POST.
- **DAX scope**: DAX queries are limited to SELECT-equivalent operations (`EVALUATE`
  statements). Mutations (`DATATABLE` with writes, `CALCULATE` on row-level filters
  that bypass RLS) are not permitted.
- **Secrets never in output**: Credentials, tokens, and internal IDs must never appear
  in the agent's responses to the user.
- **Row limits**: DAX query results are capped at 100,000 rows per call to prevent
  runaway API usage. If the result would be larger, the agent must inform the user and
  suggest a more specific filter.
- **No PII in logs**: Do not log raw query results that may contain PII. Log only
  metadata (workspace ID, dataset ID, row count).

## Success Criteria

1. Agent can list all workspaces for a configured service principal within 5 seconds.
2. Agent correctly executes a user-supplied natural-language question as a DAX query
   with ≥90% structural accuracy on the evaluation set.
3. Dashboard tile values are returned correctly (matching the Power BI UI) for at
   least 95% of tiles in the evaluation set.
4. Agent refuses read-write operations and explains the restriction clearly.
5. Agent gracefully handles expired tokens by refreshing automatically (no user action).

## Edge Cases to Handle

1. **Empty workspace**: Workspace exists but has no reports/dashboards — return a
   clear "no items found" message rather than an error.
2. **Token expiry mid-session**: MSAL token cache should handle silent refresh; if
   it fails, surface a clear "re-authentication required" message.
3. **DAX syntax error**: If Claude generates invalid DAX, catch the 400/error response
   from the API and ask the user to rephrase, or try one self-correction iteration.
4. **Large result sets**: If a DAX query returns >10,000 rows, truncate to 1,000 and
   note the truncation prominently.
5. **Service principal lacks workspace access**: Return a clear "access denied for
   workspace X" message rather than a generic error.
6. **Power BI Premium-only features**: Some endpoints (e.g., executeQueries) require
   Premium capacity. Detect the 403/404 response and inform the user that Premium
   capacity is needed.
