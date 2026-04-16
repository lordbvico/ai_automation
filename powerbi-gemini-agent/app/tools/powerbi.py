"""Power BI REST API tools for the ADK agent.

All functions are read-only and return plain dicts so the ADK framework can
serialise them as tool results.  Row limits and error handling follow the
constraints in DESIGN_SPEC.md.

Power BI REST API base:  https://api.powerbi.com/v1.0/myorg
Documentation:           https://learn.microsoft.com/en-us/rest/api/power-bi/
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.tools.auth import get_auth_headers

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.powerbi.com/v1.0/myorg"
_DAX_ROW_LIMIT = 10_000  # truncate results above this count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    """HTTP GET against the Power BI REST API.

    Returns the parsed JSON body on success.  On error returns a dict with
    'status': 'error' and 'message' containing the HTTP status and reason.
    """
    url = f"{_BASE_URL}{path}"
    try:
        resp = requests.get(url, headers=get_auth_headers(), params=params, timeout=30)
    except requests.RequestException as exc:
        logger.error("GET %s failed: %s", url, exc)
        return {"status": "error", "message": str(exc)}

    if resp.status_code == 403:
        return {
            "status": "error",
            "message": (
                f"Access denied (HTTP 403) for {path}. "
                "Verify that the service principal has the required Power BI role "
                "or that a Premium capacity is available for this operation."
            ),
        }
    if not resp.ok:
        return {
            "status": "error",
            "message": f"HTTP {resp.status_code} {resp.reason} — {resp.text[:200]}",
        }
    return resp.json()


def _post(path: str, body: dict) -> dict[str, Any]:
    """HTTP POST against the Power BI REST API."""
    url = f"{_BASE_URL}{path}"
    try:
        resp = requests.post(url, headers=get_auth_headers(), json=body, timeout=60)
    except requests.RequestException as exc:
        logger.error("POST %s failed: %s", url, exc)
        return {"status": "error", "message": str(exc)}

    if resp.status_code == 403:
        return {
            "status": "error",
            "message": (
                f"Access denied (HTTP 403) for {path}. "
                "This endpoint may require a Power BI Premium capacity."
            ),
        }
    if not resp.ok:
        return {
            "status": "error",
            "message": f"HTTP {resp.status_code} {resp.reason} — {resp.text[:400]}",
        }
    return resp.json()


# ---------------------------------------------------------------------------
# Tool functions — each is registered directly with the ADK agent.
# ---------------------------------------------------------------------------


def list_workspaces() -> dict:
    """List all Power BI workspaces (groups) accessible to the service principal.

    Returns a dict with:
      - status: 'success' or 'error'
      - workspaces: list of dicts, each with id, name, type, state, and isReadOnly
    """
    data = _get("/groups")
    if "status" in data and data["status"] == "error":
        return data

    workspaces = [
        {
            "id": w.get("id"),
            "name": w.get("name"),
            "type": w.get("type"),
            "state": w.get("state"),
            "isReadOnly": w.get("isReadOnly"),
        }
        for w in data.get("value", [])
    ]
    return {"status": "success", "count": len(workspaces), "workspaces": workspaces}


def list_reports(workspace_id: str) -> dict:
    """List all reports inside a Power BI workspace.

    Args:
        workspace_id: The GUID of the Power BI workspace (group).

    Returns a dict with:
      - status: 'success' or 'error'
      - reports: list of dicts, each with id, name, datasetId, webUrl, and embedUrl
    """
    data = _get(f"/groups/{workspace_id}/reports")
    if "status" in data and data["status"] == "error":
        return data

    reports = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "datasetId": r.get("datasetId"),
            "webUrl": r.get("webUrl"),
            "embedUrl": r.get("embedUrl"),
        }
        for r in data.get("value", [])
    ]
    if not reports:
        return {"status": "success", "count": 0, "reports": [], "note": "No reports found in this workspace."}
    return {"status": "success", "count": len(reports), "reports": reports}


def list_dashboards(workspace_id: str) -> dict:
    """List all dashboards inside a Power BI workspace.

    Args:
        workspace_id: The GUID of the Power BI workspace (group).

    Returns a dict with:
      - status: 'success' or 'error'
      - dashboards: list of dicts with id, displayName, isReadOnly, webUrl, embedUrl
    """
    data = _get(f"/groups/{workspace_id}/dashboards")
    if "status" in data and data["status"] == "error":
        return data

    dashboards = [
        {
            "id": d.get("id"),
            "displayName": d.get("displayName"),
            "isReadOnly": d.get("isReadOnly"),
            "webUrl": d.get("webUrl"),
            "embedUrl": d.get("embedUrl"),
        }
        for d in data.get("value", [])
    ]
    if not dashboards:
        return {"status": "success", "count": 0, "dashboards": [], "note": "No dashboards found in this workspace."}
    return {"status": "success", "count": len(dashboards), "dashboards": dashboards}


def get_dashboard_tiles(workspace_id: str, dashboard_id: str) -> dict:
    """Retrieve all tiles from a Power BI dashboard, including their current values.

    Args:
        workspace_id: The GUID of the Power BI workspace (group).
        dashboard_id: The GUID of the dashboard.

    Returns a dict with:
      - status: 'success' or 'error'
      - tiles: list of dicts with id, title, subTitle, embedUrl, and rowSpan/colSpan
    """
    data = _get(f"/groups/{workspace_id}/dashboards/{dashboard_id}/tiles")
    if "status" in data and data["status"] == "error":
        return data

    tiles = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "subTitle": t.get("subTitle"),
            "embedUrl": t.get("embedUrl"),
            "rowSpan": t.get("rowSpan"),
            "colSpan": t.get("colSpan"),
            "datasetId": t.get("datasetId"),
            "reportId": t.get("reportId"),
        }
        for t in data.get("value", [])
    ]
    if not tiles:
        return {"status": "success", "count": 0, "tiles": [], "note": "No tiles found on this dashboard."}
    return {"status": "success", "count": len(tiles), "tiles": tiles}


def list_datasets(workspace_id: str) -> dict:
    """List all datasets in a Power BI workspace.

    Args:
        workspace_id: The GUID of the Power BI workspace (group).

    Returns a dict with:
      - status: 'success' or 'error'
      - datasets: list of dicts with id, name, configuredBy, isRefreshable,
                  and addRowsAPIEnabled
    """
    data = _get(f"/groups/{workspace_id}/datasets")
    if "status" in data and data["status"] == "error":
        return data

    datasets = [
        {
            "id": ds.get("id"),
            "name": ds.get("name"),
            "configuredBy": ds.get("configuredBy"),
            "isRefreshable": ds.get("isRefreshable"),
            "addRowsAPIEnabled": ds.get("addRowsAPIEnabled"),
            "createdDate": ds.get("createdDate"),
        }
        for ds in data.get("value", [])
    ]
    if not datasets:
        return {"status": "success", "count": 0, "datasets": [], "note": "No datasets found in this workspace."}
    return {"status": "success", "count": len(datasets), "datasets": datasets}


def list_report_pages(workspace_id: str, report_id: str) -> dict:
    """List all pages of a Power BI report with their display names.

    Args:
        workspace_id: The GUID of the Power BI workspace (group).
        report_id: The GUID of the report.

    Returns a dict with:
      - status: 'success' or 'error'
      - pages: list of dicts with name, displayName, and order
    """
    data = _get(f"/groups/{workspace_id}/reports/{report_id}/pages")
    if "status" in data and data["status"] == "error":
        return data

    pages = sorted(
        [
            {
                "name": p.get("name"),
                "displayName": p.get("displayName"),
                "order": p.get("order"),
            }
            for p in data.get("value", [])
        ],
        key=lambda p: p.get("order") or 0,
    )
    if not pages:
        return {"status": "success", "count": 0, "pages": [], "note": "No pages found in this report."}
    return {"status": "success", "count": len(pages), "pages": pages}


def execute_dax_query(workspace_id: str, dataset_id: str, dax_query: str) -> dict:
    """Execute a read-only DAX query against a Power BI dataset and return results.

    Use EVALUATE statements only. Do NOT use CREATE, ALTER, or any data-modifying
    DAX syntax — those will be rejected by the API.

    Results are truncated to 10,000 rows if the dataset returns more.

    Args:
        workspace_id: The GUID of the Power BI workspace (group).
        dataset_id: The GUID of the dataset to query.
        dax_query: A valid DAX query string starting with EVALUATE.

    Returns a dict with:
      - status: 'success' or 'error'
      - columns: list of column names
      - rows: list of row dicts (column_name → value)
      - row_count: number of rows returned
      - truncated: true if results were truncated
    """
    # Basic guard: only allow EVALUATE-based queries.
    stripped = dax_query.strip().upper()
    if not stripped.startswith("EVALUATE"):
        return {
            "status": "error",
            "message": (
                "Only DAX queries starting with EVALUATE are permitted. "
                "Please rewrite the query using EVALUATE."
            ),
        }

    body = {
        "queries": [{"query": dax_query}],
        "serializerSettings": {"includeNulls": True},
    }
    data = _post(f"/groups/{workspace_id}/datasets/{dataset_id}/executeQueries", body)
    if "status" in data and data["status"] == "error":
        return data

    try:
        result_table = data["results"][0]["tables"][0]
        rows_raw = result_table.get("rows", [])
    except (KeyError, IndexError) as exc:
        return {"status": "error", "message": f"Unexpected API response shape: {exc}"}

    truncated = len(rows_raw) > _DAX_ROW_LIMIT
    rows_raw = rows_raw[:_DAX_ROW_LIMIT]

    # Strip the "[TableName]" prefix Power BI adds to column names.
    def _clean_key(k: str) -> str:
        return k.split("]")[-1].lstrip(".") if "]" in k else k

    rows = [{_clean_key(k): v for k, v in row.items()} for row in rows_raw]
    columns = list(rows[0].keys()) if rows else []

    result: dict[str, Any] = {
        "status": "success",
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }
    if truncated:
        result["note"] = (
            f"Results truncated to {_DAX_ROW_LIMIT:,} rows. "
            "Add filters to your query to reduce the result set."
        )
    return result


def get_dataset_datasources(workspace_id: str, dataset_id: str) -> dict:
    """Return the data source connections configured for a Power BI dataset.

    This reveals what underlying databases, files, or services the dataset
    connects to (e.g. SQL Server, Azure Synapse, SharePoint).

    Args:
        workspace_id: The GUID of the Power BI workspace (group).
        dataset_id: The GUID of the dataset.

    Returns a dict with:
      - status: 'success' or 'error'
      - datasources: list of dicts with datasourceType, connectionDetails, and
                     datasourceId
    """
    data = _get(f"/groups/{workspace_id}/datasets/{dataset_id}/datasources")
    if "status" in data and data["status"] == "error":
        return data

    datasources = [
        {
            "datasourceType": ds.get("datasourceType"),
            "datasourceId": ds.get("datasourceId"),
            "connectionDetails": ds.get("connectionDetails"),
        }
        for ds in data.get("value", [])
    ]
    return {"status": "success", "count": len(datasources), "datasources": datasources}
