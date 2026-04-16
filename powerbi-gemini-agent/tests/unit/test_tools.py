"""Unit tests for Power BI tool functions.

These tests mock the HTTP layer so no live credentials are required.
Run with: pytest tests/unit/
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.tools.powerbi as pbi


def _mock_resp(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = status_code < 400
    resp.status_code = status_code
    resp.reason = "OK" if status_code < 400 else "Error"
    resp.text = ""
    resp.json.return_value = json_data
    return resp


@patch("app.tools.powerbi.get_auth_headers", return_value={"Authorization": "Bearer test"})
@patch("app.tools.powerbi.requests.get")
def test_list_workspaces_success(mock_get, _mock_auth):
    mock_get.return_value = _mock_resp(
        {"value": [{"id": "ws1", "name": "Finance", "type": "Workspace", "state": "Active", "isReadOnly": False}]}
    )
    result = pbi.list_workspaces()
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["workspaces"][0]["name"] == "Finance"


@patch("app.tools.powerbi.get_auth_headers", return_value={"Authorization": "Bearer test"})
@patch("app.tools.powerbi.requests.get")
def test_list_workspaces_empty(mock_get, _mock_auth):
    mock_get.return_value = _mock_resp({"value": []})
    result = pbi.list_workspaces()
    assert result["status"] == "success"
    assert result["count"] == 0


@patch("app.tools.powerbi.get_auth_headers", return_value={"Authorization": "Bearer test"})
@patch("app.tools.powerbi.requests.get")
def test_list_workspaces_403(mock_get, _mock_auth):
    mock_get.return_value = _mock_resp({}, status_code=403)
    result = pbi.list_workspaces()
    assert result["status"] == "error"
    assert "403" in result["message"]


@patch("app.tools.powerbi.get_auth_headers", return_value={"Authorization": "Bearer test"})
@patch("app.tools.powerbi.requests.post")
def test_execute_dax_query_success(mock_post, _mock_auth):
    mock_post.return_value = _mock_resp(
        {
            "results": [
                {
                    "tables": [
                        {
                            "rows": [
                                {"Sales[Region]": "North", "Sales[Total]": 1000},
                                {"Sales[Region]": "South", "Sales[Total]": 800},
                            ]
                        }
                    ]
                }
            ]
        }
    )
    result = pbi.execute_dax_query("ws1", "ds1", "EVALUATE SUMMARIZE('Sales', 'Sales'[Region])")
    assert result["status"] == "success"
    assert result["row_count"] == 2
    assert result["truncated"] is False


@patch("app.tools.powerbi.get_auth_headers", return_value={"Authorization": "Bearer test"})
@patch("app.tools.powerbi.requests.post")
def test_execute_dax_query_rejects_non_evaluate(mock_post, _mock_auth):
    result = pbi.execute_dax_query("ws1", "ds1", "CREATE TABLE foo (x INT)")
    assert result["status"] == "error"
    assert "EVALUATE" in result["message"]
    mock_post.assert_not_called()  # Guard prevents the HTTP call entirely
