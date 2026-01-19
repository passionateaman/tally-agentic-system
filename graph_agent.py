#graph_agent.py
import os
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from tools.tally_report_tool import get_report as get_report_tool
from tools.report_lookup import lookup_tally_report
from tools.json_normalizer import normalize_report_tool, _aggregate_parent_rows

# ============================================================
#  OPTIONAL LLM (USED ONLY FOR FILTERING)
# ============================================================

from langchain_google_genai import ChatGoogleGenerativeAI

_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
_LLM = None
if _API_KEY:
    _LLM = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp"),
        temperature=0.0,
        google_api_key=_API_KEY,
        max_retries=0,
    )

# ============================================================
#  HELPERS
# ============================================================

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def should_show_full_report(query: str) -> bool:
    """
    Detect if user wants FULL report
    """
    q = query.lower()
    full_keywords = [
        "full", "complete", "entire", "all", "total", 
        "whole", "everything", "puri", "saari", "sab"
    ]
    return any(kw in q for kw in full_keywords)


def extract_explicit_fields(query: str, available_labels: List[str]) -> Optional[List[str]]:
    """
    Extract explicitly mentioned field names from query
    Returns None if no explicit fields found
    """
    q = query.lower()
    
    # Remove common words
    noise_words = [
        "show", "display", "plot", "graph", "chart", "pie", "bar", "line",
        "me", "the", "a", "an", "of", "in", "from", "for", "balance", "sheet",
        "profit", "loss", "stock", "summary", "only", "just", "give"
    ]
    
    # Check for comma-separated or "and" separated items
    # Example: "Cash, Bank, Debtors" or "Cash and Bank"
    parts = re.split(r'[,;&]|\band\b', q)
    
    matched_fields = []
    available_lower = [_norm(label) for label in available_labels]
    label_map = {_norm(label): label for label in available_labels}
    
    for part in parts:
        cleaned = _norm(part)
        
        # Remove noise words
        words = cleaned.split()
        words = [w for w in words if w not in noise_words]
        cleaned = " ".join(words)
        
        if not cleaned:
            continue
        
        # Exact match
        if cleaned in available_lower:
            matched_fields.append(label_map[cleaned])
            continue
        
        # Partial match (for multi-word labels)
        for norm_label, orig_label in label_map.items():
            if cleaned in norm_label or norm_label in cleaned:
                if len(cleaned) > 3:  # Avoid too short matches
                    matched_fields.append(orig_label)
                    break
    
    # Return None if no fields found (means show full report)
    return matched_fields if matched_fields else None


# ============================================================
#  LLM BASED FILTER (ENHANCED)
# ============================================================

def llm_filter_rows(rows, user_query, allowed_labels):
    """
    Use LLM to intelligently select fields from user query
    """
    if not _LLM or not rows:
        return rows

    prompt = f"""
You are a strict label-selection engine.

User request:
"{user_query}"

Available labels (ONLY choose from these):
{json.dumps(allowed_labels, indent=2)}

Rules:
- Select ONLY labels explicitly mentioned or clearly implied by the user
- Do NOT add extra labels on your own
- Do NOT infer or expand the scope
- Do NOT include related, parent, child, or similar labels unless explicitly requested
- If the user requests N items, return AT MOST N labels
- If none match clearly, return an empty list

Output format:
A JSON array of selected label strings.
Example:
["Capital Account", "Current Assets"]
"""

    try:
        resp = _LLM.invoke(prompt)
        labels = json.loads(resp.content)

        if isinstance(labels, list) and labels:
            return [r for r in rows if r["label"] in labels]

    except Exception:
        pass

    return rows


# ============================================================
#  SMART FILTERING LOGIC
# ============================================================

def apply_smart_filter(rows: List[Dict], user_query: str) -> List[Dict]:
    """
    Smart filtering based on user intent:
    1. If "full/complete/all" → return all rows
    2. If explicit fields found → return only those
    3. If "only" keyword → use LLM
    4. Otherwise → return all rows (default)
    """
    
    # Check #1: User wants full report?
    if should_show_full_report(user_query):
        return rows
    
    available_labels = [r["label"] for r in rows]
    
    # Check #2: Explicit fields mentioned?
    explicit_fields = extract_explicit_fields(user_query, available_labels)
    
    if explicit_fields:
        # User specified exact fields
        return [r for r in rows if r["label"] in explicit_fields]
    
    # Check #3: "only" keyword present?
    if "only" in user_query.lower():
        # Use LLM for intelligent filtering
        return llm_filter_rows(rows, user_query, available_labels)
    
    # Default: Show full report
    return rows


# ============================================================
#  COMMAND MODEL
# ============================================================

@dataclass
class GraphCommand:
    chart_type: str
    report_name: str
    company_name: str


# ============================================================
#  QUERY PARSER
# ============================================================

def parse_user_query(user_query: str, company_name: str) -> GraphCommand:
    if not company_name:
        raise ValueError("Company not selected")

    q = user_query.lower()

    # Chart type detection (keep existing logic)
    chart_type = "bar"
    if "pie" in q or "pie chart" in q:
        chart_type = "pie"
    elif "line" in q or "line graph" in q or "line chart" in q:
        chart_type = "line"
    elif "bar" in q or "bar chart" in q or "bar graph" in q:
        chart_type = "bar"

    #NEW: Use RAG-powered lookup instead of keyword matching
    report_name = lookup_tally_report(user_query)
    
    if not report_name:
        raise ValueError(
            "Unable to determine report. Please rephrase your question."
        )

    return GraphCommand(
        chart_type=chart_type,
        report_name=report_name,
        company_name=company_name,
    )
# ============================================================
#  FETCH REPORT
# ============================================================
def fetch_tally_report(cmd: GraphCommand, static_vars=None) -> Dict[str, Any]:
    candidates = [cmd.report_name]

    if cmd.report_name == "Profit & Loss":
        candidates = [
            "ProfitAndLoss",
            "Trading & Profit & Loss",
            "Profit & Loss A/c",
        ]

    for name in candidates:
        res = get_report_tool.run({
            "company_name": cmd.company_name,
            "report_name": name,
            "static_vars": static_vars,
        })
        if isinstance(res, dict) and res.get("ENVELOPE"):
            return res

    return {}
# ============================================================
#  VEGA LAYOUT
# ============================================================
def generate_vega_layout(chart_type: str, numeric_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    if chart_type == "bar" and numeric_fields and len(numeric_fields) > 1:
        return {
            "transform": [
                {
                    "fold": numeric_fields,
                    "as": ["metric", "amount"]
                }
            ],
            "mark": {"type": "bar"},
            "encoding": {
                "x": {
                    "field": "label",
                    "type": "ordinal",
                    "title": "Month"
                },
                "xOffset": {
                    "field": "metric"
                },
                "y": {
                    "field": "amount",
                    "type": "quantitative",
                    "title": "Amount (₹)"
                },
                "color": {
                    "field": "metric",
                    "type": "nominal",
                    "title": "Type"
                },
                "tooltip": [
                    {"field": "label", "title": "Label"},
                    {"field": "metric", "title": "Type"},
                    {"field": "amount", "title": "Amount"}
                ]
            }
        }

    if chart_type == "pie":
        return {
            "mark": {"type": "arc"},
            "encoding": {
                "theta": {"field": "value", "type": "quantitative", "aggregate": "sum"},
                "color": {"field": "label", "type": "nominal"},
                "tooltip": [
                    {"field": "label"},
                    {"field": "value"},
                ],
            },
            "view": {"stroke": None},
        }
    if chart_type == "line":
        return {
            "mark": {"type": "line", "point": True},
            "encoding": {
                "x": {
                    "field": "label",
                    "type": "ordinal",   # KEY FIX
                    "axis": {"labelAngle": -45}
                },
                "y": {
                    "field": "value",
                    "type": "quantitative"
                },
                "tooltip": [
                    {"field": "label", "type": "nominal"},
                    {"field": "value", "type": "quantitative"},
                ],
            },
        }

    return {
        "mark": chart_type,
        "encoding": {
            "x": {"field": "label", "type": "nominal"},
            "y": {"field": "value", "type": "quantitative"},
            "color": {"field": "label", "type": "nominal"},
            "tooltip": [
                {"field": "label"},
                {"field": "value"},
            ],
        },
    }
# ============================================================
#  MAIN GRAPH PIPELINE
# ============================================================

def run_graph_pipeline(
    user_query: str,
    company_name: str,
    static_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    # 1️⃣ Parse
    cmd = parse_user_query(user_query, company_name)

    # 2️⃣ Fetch report
    raw = fetch_tally_report(cmd, static_vars)

    # 3️⃣ Normalize
    normalized = normalize_report_tool(raw)
    rows = normalized.get("rows", [])

    # 4️⃣ Aggregate parents for Balance Sheet
    if cmd.report_name == "Balance Sheet":
        rows = _aggregate_parent_rows(rows)

    rows = [
    r for r in rows
    if any(
        r.get(k) is not None
        for k in ("value","inflow","outflow","net_flow","credit","debit","closing_balance")
    )
]



    # ========================================================
    # SMART FILTERING (NEW LOGIC)
    # ========================================================
    rows = apply_smart_filter(rows, user_query)
    # ========================================================

    POSSIBLE_NUMERIC_FIELDS = [
    "credit",
    "debit",
    "closing_balance",
    "inflow",
    "outflow",
    "net_flow",
    "value"
]
    numeric_fields = []

    if rows:
        for k in POSSIBLE_NUMERIC_FIELDS:
            if k in rows[0] and k not in numeric_fields:
                 numeric_fields.append(k)



    if rows:
        sample = rows[0]
        for k, v in sample.items():
            if k in ("section", "label"):
                continue
            if isinstance(v, (int, float)) and k not in numeric_fields:
                numeric_fields.append(k)


    if cmd.chart_type == "bar" and len(numeric_fields) > 1:
        vega_layout = generate_vega_layout(
            chart_type="bar",
            numeric_fields=numeric_fields
        )
    else:
        vega_layout = generate_vega_layout(cmd.chart_type)





    vega_spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": rows},
        **vega_layout,
    }

    return {
        "status": "ok",
        "command": cmd.__dict__,
        "normalized": {
            "columns": normalized.get("columns", ["section", "label", "value"]),
            "rows": rows,
        },
        "vega_spec": vega_spec,
    }


# ============================================================
#  NL ENTRYPOINT
# ============================================================

def run_nl_graph_pipeline(
    question: str,
    company_name: str,
    static_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return run_graph_pipeline(
        user_query=question,
        company_name=company_name,
        static_vars=static_vars,
    )
# ============================================================
#  TABLE PIPELINE 
# ============================================================

def run_table_pipeline(
    question: str,
    company_name: str,
    static_vars: Optional[Dict[str, Any]] = None,
):

    if not company_name:
        return {
            "output_type": "table",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "report_used": None,
        }

    cmd = parse_user_query(question, company_name)
    raw = fetch_tally_report(cmd, static_vars)
    normalized = normalize_report_tool(raw)

    rows = normalized.get("rows", [])

    if cmd.report_name == "Balance Sheet":
        rows = _aggregate_parent_rows(rows)

    rows = [
    r for r in rows
    if any(
        r.get(k) is not None
        for k in (
            "value",
            "credit",
            "debit",
            "closing_balance",  
            "inflow",
            "outflow",
            "net_flow",
        )
    )
]
    # FIX: Sales Register should NOT show CashFlow columns
    if cmd.report_name.lower() == "sales register":
        cleaned = []
        for r in rows:
            cleaned.append({
                "section": r.get("section"),
                "label": r.get("label"),
                "credit": r.get("credit"),
                "closing_balance": r.get("closing_balance"),
            })
        rows = cleaned

    return {
        "output_type": "table",
        "columns": normalized.get("columns", ["label", "value"]),
        "rows": rows,
        "row_count": len(rows),
        "report_used": cmd.report_name,
    }