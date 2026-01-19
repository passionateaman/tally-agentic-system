# tools/fetch_report.py
from typing import Dict, Any, Optional, List
from tools import tally_report_tool
from langchain.tools import tool
import json


# You can keep or simplify these; they do NOT change the report name, only static vars.
STATIC_VARIANTS = [
    None,
    {"EXPLODEFLAG": "Yes", "SVEXPORTFORMAT": "$$SysName:XML"},
    {
        "EXPLODEFLAG": "Yes",
        "SVEXPORTFORMAT": "$$SysName:XML",
        "SVFromDate": "2024-04-01",
        "SVToDate": "2025-03-31",
    },
    {"SVFromDate": "2024-04-01", "SVToDate": "2025-03-31"},
]


def _call_tool_like(tool_obj, company: str, report: str, static_vars: Optional[dict] = None):
    """
    Helper to call tally_report_tool.get_report regardless of whether it's a LangChain tool,
    a plain function
    """
    last_exc = None
    try:
        if hasattr(tool_obj, "invoke"):
            return tool_obj.invoke(
                {"company_name": company, "report_name": report, "static_vars": static_vars}
            )
    except Exception as e:
        last_exc = e
    try:
        if hasattr(tool_obj, "run"):
            try:
                return tool_obj.run(
                    {"company_name": company, "report_name": report, "static_vars": static_vars}
                )
            except TypeError:
                return tool_obj.run(
                    company_name=company, report_name=report, static_vars=static_vars
                )
    except Exception as e:
        last_exc = e
    try:
        return tool_obj(company_name=company, report_name=report, static_vars=static_vars)
    except Exception as e:
        last_exc = e
    try:
        return tool_obj(
            {"company_name": company, "report_name": report, "static_vars": static_vars}
        )
    except Exception as e:
        last_exc = e
    try:
        underlying = getattr(tool_obj, "func", None) or getattr(tool_obj, "__wrapped__", None)
        if underlying and callable(underlying):
            try:
                return underlying(
                    company_name=company, report_name=report, static_vars=static_vars
                )
            except TypeError:
                return underlying(
                    {"company_name": company, "report_name": report, "static_vars": static_vars}
                )
    except Exception as e:
        last_exc = e
    raise last_exc or RuntimeError("Unable to call tally_report_tool.get_report.")


def _looks_like_not_found(resp: Any) -> bool:
    """
    Detect Tally 'report not found' responses.

    Handles shapes like:
    {
      "RESPONSE": {
        "LINEERROR": "Could not find Report 'XYZ'!"
      }
    }
    """
    try:
        # Direct string
        if isinstance(resp, str):
            if "Could not find Report" in resp or "Could not set 'SVCurrentCompany'" in resp:
                return True
            return False

        if not isinstance(resp, dict):
            return False

        # Top-level LINEERROR
        v = resp.get("LINEERROR")
        if isinstance(v, str) and (
            "Could not find Report" in v or "Could not set 'SVCurrentCompany'" in v
        ):
            return True

        # Nested under RESPONSE -> LINEERROR
        if isinstance(resp.get("RESPONSE"), dict):
            v2 = resp["RESPONSE"].get("LINEERROR")
            if isinstance(v2, str) and (
                "Could not find Report" in v2 or "Could not set 'SVCurrentCompany'" in v2
            ):
                return True

        # Sometimes server returns raw text
        raw = resp.get("raw")
        if isinstance(raw, str):
            if "Could not find Report" in raw or "Could not set 'SVCurrentCompany'" in raw:
                return True

        # Fallback: scan entire dict as text
        try:
            text = json.dumps(resp, default=str)
            if "Could not find Report" in text or "Could not set 'SVCurrentCompany'" in text:
                return True
        except Exception:
            pass

        return False
    except Exception:
        return False


def _try_exact_name_with_static_variants(
    company: str, report_name: str, static_list: List[Optional[dict]]
):
    """
    Try the *exact* report name with each static_vars variant.
    No aliasing, no renaming.
    """
    tool_obj = getattr(tally_report_tool, "get_report", None)
    if tool_obj is None:
        return None, {"error": "tally_report_tool.get_report not found"}

    meta: Dict[str, Any] = {report_name: []}

    for sv in static_list:
        try:
            parsed = _call_tool_like(tool_obj, company, report_name, sv)
        except Exception as e:
            meta[report_name].append(
                {"static_vars": sv, "error": f"{type(e).__name__}: {e}"}
            )
            continue

        meta[report_name].append(
            {
                "static_vars": sv,
                "result": parsed
                if isinstance(parsed, dict)
                else {"repr": str(parsed)[:400]},
            }
        )

        # If clearly "not found", continue
        if _looks_like_not_found(parsed):
            continue

        # If dict with some keys, accept as success
        if isinstance(parsed, dict):
            return parsed, meta

    return None, meta


def fetch_report_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload keys:
      - company_name / company
      - report_name / report
      - try_alternatives: bool (ignored now; name is not changed)
      - static_vars: optional dict

    Returns:
      {
        "report": <parsed or error>,
        "report_used": "<name used>",
        "meta": {...}
      }
    """
    company = payload.get("company_name") or payload.get("company")
    report = payload.get("report_name") or payload.get("report")
    user_static = payload.get("static_vars") or payload.get("staticVars") or None

    if not company or not report:
        return {
            "report": {"error": "missing_params", "detail": "company_name and report_name required"},
            "report_used": None,
            "meta": {},
        }

    static_list = [user_static] + STATIC_VARIANTS if user_static else STATIC_VARIANTS

    parsed, meta = _try_exact_name_with_static_variants(company, report, static_list)
    if parsed is not None:
        return {"report": parsed, "report_used": report, "meta": {"attempts": meta}}

    # If nothing worked, surface a clear error instead of pretending success
    return {
        "report": {
            "error": "report_not_found",
            "detail": f"Tally could not find report '{report}' for company '{company}'.",
            "raw_meta": meta,
        },
        "report_used": report,
        "meta": {"attempts": meta},
    }


@tool("fetch_report")
def fetch_report_langchain(
    company_name: str,
    report_name: str,
    try_alternatives: bool = True,  # kept for compatibility but ignored
    static_vars: Optional[Dict[str, Any]] = None,
):
    """
    High-level report fetcher for agents.

    IMPORTANT:
    - Uses the report name exactly as given (no aliasing or renaming).
    - Tries a few static variable variants (date ranges, explode flag) to increase success chance.
    - Returns a structured error if Tally says the report is not found.
    """
    payload = {
        "company_name": company_name,
        "report_name": report_name,
        "try_alternatives": try_alternatives,  # ignored for name mapping
        "static_vars": static_vars,
    }
    return fetch_report_tool(payload)
