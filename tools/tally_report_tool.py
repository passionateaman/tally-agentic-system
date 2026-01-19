# tools/tally_report_tool.py
import requests
import xml.etree.ElementTree as ET
from langchain.tools import tool
from dotenv import load_dotenv
import os
from typing import Optional, Dict, Any

load_dotenv()
TALLY_URL = os.getenv("TALLY_HTTP_HOST")


def build_report_envelope(report_name: str, company_name: str, static_vars: Optional[Dict[str, Any]] = None) -> str:
    """
    Build Tally XML envelope. static_vars should be a dict of STATICVARIABLES to add,
    e.g. {"SVFromDate":"2025-04-01","SVToDate":"2025-03-31","SVCurrentCompany":"My Company"}
    """
    def esc(s):
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    rid = esc(report_name)
    cname = esc(company_name)

    static_vars = static_vars or {}
    if "SVCurrentCompany" not in static_vars:
        static_vars["SVCurrentCompany"] = company_name

    sv_lines = []
    for k, v in static_vars.items():
        if v is None:
            continue
        sv_lines.append(f"            <{esc(k)}>{esc(v)}</{esc(k)}>")

    static_block = "\n".join(sv_lines)

    return f"""
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Export Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>{rid}</REPORTNAME>
        <STATICVARIABLES>
{static_block}
        </STATICVARIABLES>
      </REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>
""".strip()


def xml_to_dict(elem: ET.Element) -> Any:
    """
    Convert an ElementTree element into nested Python structures.
    - Repeated child tags become lists (preserve order).
    - Leaves become text (strings) or None.
    """
    # If element has no children, return its text (possibly None)
    children = list(elem)
    if not children:
        text = elem.text
        return text.strip() if isinstance(text, str) and text.strip() != "" else None

    result: Dict[str, Any] = {}
    for child in children:
        tag = child.tag
        child_val = xml_to_dict(child)

        # If tag already exists, convert to list or append
        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(child_val)
        else:
            # first occurrence: store directly (may later be converted to list)
            result[tag] = child_val

    return result


@tool("get_report")
def get_report(company_name: str, report_name: str, static_vars: Optional[Dict[str, Any]] = None):
    """
    Fetch report from Tally. Pass `static_vars` as a dict to control date ranges or other SVs.
    Example:
      get_report("My Co", "Balance Sheet", {"SVFromDate":"2024-04-01","SVToDate":"2025-03-31"})
    Returns parsed dict (root element converted). If parsing fails, returns {"raw": "<xml...>"}.
    """
    if not TALLY_URL:
        return {"error": "Missing TALLY_HTTP_HOST in .env"}

    if not company_name:
        return {"error": "company_name required"}
    if not report_name:
        return {"error": "report_name required"}

    xml_payload = build_report_envelope(report_name, company_name, static_vars=static_vars)

    try:
        response = requests.post(TALLY_URL, data=xml_payload, timeout=30)
    except Exception as e:
        return {"error": f"HTTP connection failed: {str(e)}"}

    raw_xml = response.text.strip()
    if not raw_xml:
        return {"error": "Tally returned an empty response"}

    # Try XML parsing → return structured dict where repeated tags are lists
    try:
        root = ET.fromstring(raw_xml)
        parsed = {root.tag: xml_to_dict(root)}
        return parsed
    except Exception:
        # Sometimes Tally returns HTML or other wrapper → return raw XML for inspection
        return {"raw": raw_xml}
