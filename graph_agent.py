#graph_agent.py
import cmd
import os
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from tools.tally_report_tool import get_report as get_report_tool
from tools.report_lookup import lookup_tally_report
from tools.json_normalizer import normalize_report_tool, _aggregate_parent_rows


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


#def should_show_full_report(query: str) -> bool:
    """
    Detect if user wants FULL report
    """
   # q = query.lower()
   # full_keywords = [
     #   "full", "complete", "entire", "all", "total", 
      #  "whole", "everything"
   # ]
    #return any(kw in q for kw in full_keywords)


#def extract_explicit_fields(query: str, available_labels: List[str]) -> Optional[List[str]]:
    """
    Extract explicitly mentioned field names from query
    Returns None if no explicit fields found
    """
    #q = query.lower()
    
    # Remove common words
    #noise_words = [
      #  "show", "display", "plot", "graph", "chart", "pie", "bar", "line",
      #  "me", "the", "a", "an", "of", "in", "from", "for", "balance", "sheet",
      #  "profit", "loss", "stock", "summary", "only", "just", "give"
   # ]
    
    # Check for comma-separated or "and" separated items
    # Example: "Cash, Bank, Debtors" or "Cash and Bank"
    #parts = re.split(r'[,;&]|\band\b', q)
    
    #matched_fields = []
    #available_lower = [_norm(label) for label in available_labels]
    #label_map = {_norm(label): label for label in available_labels}
    
    #for part in parts:
       # cleaned = _norm(part)
        
        # Remove noise words
        #words = cleaned.split()
        #words = [w for w in words if w not in noise_words]
       # cleaned = " ".join(words)
        
       # if not cleaned:
        #    continue
        
        # Exact match
       # if cleaned in available_lower:
         #   matched_fields.append(label_map[cleaned])
          #  continue
        
        # Partial match (for multi-word labels)
        #for norm_label, orig_label in label_map.items():
         #   if cleaned in norm_label or norm_label in cleaned:
          #      if len(cleaned) > 3:  # Avoid too short matches
           #         matched_fields.append(orig_label)
            #        break
    
    # Return None if no fields found (means show full report)
    #return matched_fields if matched_fields else None


# ============================================================
#  LLM BASED FILTER 
# ============================================================

def llm_filter_rows(rows, user_query, allowed_labels):
    """
    Pure LLM-based filtering.
    Handles ALL scenarios intelligently.
    """
    if not _LLM or not rows:
        return rows

    prompt = f"""
You are an intelligent data filter for financial reports with deep understanding of temporal queries.

USER QUERY: "{user_query}"

AVAILABLE DATA LABELS (these are the actual items in the report):
{json.dumps(allowed_labels, indent=2)}

TASK: Determine which labels should be included in the visualization.

CRITICAL TEMPORAL UNDERSTANDING:

1. "TILL" / "UNTIL" / "UP TO" KEYWORDS:
   - "Show cash flow till December" → Include ALL months from start till December
   - "Sales till June" → Include ALL months up to and including June
   - "Data until March" → Include ALL months up to and including March
   
2. "FROM X TO Y" PATTERNS:
   - "Sales from April to June" → Include April, May, June (all months in range)
   - "Data from Jan to Mar" → Include January, February, March
   
3. SPECIFIC MONTHS/PERIODS:
   - "Show April and May" → ONLY April and May
   - "Only June sales" → ONLY June
   - "Compare March vs September" → ONLY March and September

4. FULL/ALL PATTERNS:
   - "Show monthly sales" → ALL available months
   - "Analyze balance sheet" → ALL available accounts
   - "Plot all items" → ALL available items
   - "Complete data" → ALL labels

5. FIELD VS LABEL DISTINCTION:
   - Field names: inflow, outflow, credit, debit, value, closing_balance
   - Label names: Actual data items (months, accounts, items)
   - "Show outflow" → Return ALL labels (user wants outflow FIELD for all items)
   - "Show April" → Return ONLY April (user wants specific LABEL)

MONTH NAME RECOGNITION:
- Full names: January, February, March, April, May, June, July, August, September, October, November, December
- Short names: Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
- Abbreviations: Apr-2024, May-2024, etc.

RANGE CALCULATION EXAMPLES:

Query: "Show cash flow till December"
Available: ["April", "May", "June", "July", "August", "September", "October", "November", "December"]
Analysis: "till December" means from START to December (inclusive)
Output: ["April", "May", "June", "July", "August", "September", "October", "November", "December"]

Query: "Sales from May to August"
Available: ["April", "May", "June", "July", "August", "September"]
Analysis: "from May to August" means May through August (inclusive)
Output: ["May", "June", "July", "August"]

Query: "Show only Capital Account and Loans"
Available: ["Capital Account", "Loans", "Current Assets", "Fixed Assets"]
Analysis: "only" keyword with specific items
Output: ["Capital Account", "Loans"]

Query: "Compare April vs May"
Available: ["April", "May", "June", "July"]
Analysis: "compare" with two specific items
Output: ["April", "May"]

Query: "Show monthly sales for FY 2024-25"
Available: ["Apr-2024", "May-2024", "Jun-2024", "Jul-2024", "Aug-2024"]
Analysis: Generic monthly request - show all available
Output: ["Apr-2024", "May-2024", "Jun-2024", "Jul-2024", "Aug-2024"]

Query: "Projected cash outflow per month"
Available: ["January", "February", "March", "April", "May"]
Analysis: "per month" means show all months, "outflow" is a field name
Output: ["January", "February", "March", "April", "May"]

Query: "Balance sheet breakdown"
Available: ["Capital Account", "Loans", "Current Liabilities", "Current Assets", "Fixed Assets"]
Analysis: Generic breakdown request - show all
Output: ["Capital Account", "Loans", "Current Liabilities", "Current Assets", "Fixed Assets"]

Query: "Stock items by value"
Available: ["Item A", "Item B", "Item C", "Item D", "Item E"]
Analysis: Generic analysis request - show all items
Output: ["Item A", "Item B", "Item C", "Item D", "Item E"]

Query: "Show inflow and outflow"
Available: ["April", "May", "June"]
Analysis: "inflow" and "outflow" are FIELD names, not labels - show all periods
Output: ["April", "May", "June"]

Query: "April sales only"
Available: ["April", "May", "June"]
Analysis: "only" with specific month
Output: ["April"]

DECISION LOGIC:

Step 1: Check if query mentions FIELD names (inflow, outflow, credit, debit, value)
        → If yes, return ALL labels (user wants that field for all items)

Step 2: Check for temporal range keywords (till, until, from...to, up to)
        → If yes, calculate the range and return all labels in that range

Step 3: Check for specific label mentions with limiting keywords (only, just, compare)
        → If yes, return ONLY those specific labels

Step 4: Check for generic/analysis requests (show, analyze, plot, visualize, breakdown)
        → If yes and no specific items mentioned, return ALL labels

Step 5: Default behavior
        → If uncertain, return ALL labels (better to show more than miss data)

OUTPUT FORMAT:
Return ONLY a valid JSON array of label strings.
DO NOT include explanations, markdown, or code blocks.

Examples:
["April", "May", "June", "July", "August", "September", "October", "November", "December"]
["Capital Account", "Loans"]
["Item A", "Item B", "Item C"]

Now analyze the user query and return the appropriate labels:
"""

    try:
        resp = _LLM.invoke(prompt)
        content = resp.content.strip()
        
        # Remove markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        
        labels = json.loads(content)

        if isinstance(labels, list):
            # Validate that returned labels exist in available_labels
            valid_labels = [l for l in labels if l in allowed_labels]
            
            if len(valid_labels) == 0:
                # LLM returned invalid labels or empty list
                print(f"LLM returned invalid/empty labels, using all {len(rows)} rows")
                return rows
            
            # Filter rows based on LLM decision
            filtered = [r for r in rows if r["label"] in valid_labels]
            
            print(f"LLM filtered: {len(rows)} → {len(filtered)} rows")
            print(f"   Selected labels: {valid_labels[:5]}{'...' if len(valid_labels) > 5 else ''}")
            
            return filtered

    except Exception as e:
        print(f"LLM filtering error: {e}, using all rows")
        return rows

    # Fallback: return all rows if something went wrong
    return rows


# ============================================================
#  SMART FILTERING LOGIC 
# ============================================================

def apply_smart_filter(rows: List[Dict], user_query: str) -> List[Dict]:
    """
    Pure LLM-based filtering - no hardcoded rules.
    """
    if not rows:
        return rows
    
    available_labels = [r["label"] for r in rows]
    
    # Direct LLM filtering - no pre-checks
    filtered_rows = llm_filter_rows(rows, user_query, available_labels)
    
    return filtered_rows

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
#  LLM-BASED VEGA SPEC GENERATION
# ============================================================

def generate_vega_spec_with_llm(
    rows: List[Dict],
    user_query: str,
    chart_type: str,
    numeric_fields: List[str]
) -> Optional[Dict[str, Any]]:
    """
    Use LLM to generate beautiful, colorful Vega-Lite specs based on user query.
    Returns None if LLM fails (fallback to deterministic method).
    """
    if not _LLM or not rows:
        return None
    
    # Sample data for LLM (limit to 5 rows for token efficiency)
    sample_data = rows[:5]
    
    prompt = f"""
You are a Vega-Lite specification generator that creates BEAUTIFUL, COLORFUL visualizations.

USER QUERY: {user_query}
CHART TYPE: {chart_type}
AVAILABLE FIELDS: {numeric_fields}

SAMPLE DATA (first 5 rows):
{json.dumps(sample_data, indent=2)}

TASK: Generate a stunning Vega-Lite v5 specification that:
1. Uses ONLY the fields mentioned in the user query
2. Creates a {chart_type} chart
3. Is COLORFUL with distinct colors for each category
4. Includes a LEGEND for easy identification
5. Has clear tooltips showing all relevant data
6.Is valid Vega-Lite JSON

MANDATORY VISUALIZATION REQUIREMENTS:

COLORS (CRITICAL):
- ALWAYS use "color" encoding with "label" field for categorical coloring
- Use "type": "nominal" for categorical color schemes
- Colors should be DISTINCT and VIBRANT (Vega-Lite's default scheme)
- NEVER use plain blue - categories should have different colors

LEGEND (CRITICAL):
- ALWAYS include legend with title
- Legend should be visible on the right side
- Use meaningful legend titles (e.g., "Account", "Month", "Category")

TOOLTIPS (CRITICAL):
- Include ALL relevant fields in tooltip
- Show "label" + all numeric fields
- Format: [{{"field": "label"}}, {{"field": "value"}}, ...]

CHART-SPECIFIC TEMPLATES:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BAR CHART (SINGLE METRIC) - COLORFUL VERSION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "mark": "bar",
  "encoding": {{
    "x": {{
      "field": "label",
      "type": "nominal",
      "axis": {{
        "title": "Category",
        "labelAngle": -45
      }}
    }},
    "y": {{
      "field": "METRIC_NAME",
      "type": "quantitative",
      "axis": {{"title": "Amount (₹)"}}
    }},
    "color": {{
      "field": "label",
      "type": "nominal",
      "legend": {{"title": "Items"}},
      "scale": {{"scheme": "category20"}}
    }},
    "tooltip": [
      {{"field": "label", "type": "nominal", "title": "Item"}},
      {{"field": "METRIC_NAME", "type": "quantitative", "title": "Value", "format": ",.2f"}}
    ]
  }}
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BAR CHART (MULTIPLE METRICS - GROUPED) - COLORFUL VERSION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "transform": [
    {{
      "fold": ["metric1", "metric2"],
      "as": ["Metric Type", "Amount"]
    }}
  ],
  "mark": "bar",
  "encoding": {{
    "x": {{
      "field": "label",
      "type": "ordinal",
      "axis": {{
        "title": "Month",
        "labelAngle": -45
      }}
    }},
    "xOffset": {{"field": "Metric Type"}},
    "y": {{
      "field": "Amount",
      "type": "quantitative",
      "axis": {{"title": "Amount (₹)"}}
    }},
    "color": {{
      "field": "Metric Type",
      "type": "nominal",
      "legend": {{"title": "Type"}},
      "scale": {{"scheme": "set2"}}
    }},
    "tooltip": [
      {{"field": "label", "title": "Month"}},
      {{"field": "Metric Type", "title": "Type"}},
      {{"field": "Amount", "title": "Amount", "format": ",.2f"}}
    ]
  }}
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINE CHART - COLORFUL VERSION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINE CHART - COLORFUL VERSION:
{{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "layer": [
    {{
      "mark": {{
        "type": "line",
        "strokeWidth": 2,
        "color": "#6b7280"
      }},
      "encoding": {{
        "x": {{
          "field": "label",
          "type": "nominal",
          "sort": null
        }},
        "y": {{
          "field": "METRIC_NAME",
          "type": "quantitative"
        }}
      }}
    }},
    {{
      "mark": {{
        "type": "point",
        "filled": true,
        "size": 100
      }},
      "encoding": {{
        "x": {{
          "field": "label",
          "type": "nominal",
          "sort": null,
          "axis": {{
            "title": "Period",
            "labelAngle": -45
          }}
        }},
        "y": {{
          "field": "METRIC_NAME",
          "type": "quantitative",
          "axis": {{"title": "Amount (₹)"}}
        }},
        "color": {{
          "field": "label",
          "type": "nominal",
          "legend": {{"title": "Category"}},
          "scale": {{"scheme": "tableau20"}}
        }},
        "tooltip": [
          {{"field": "label", "type": "nominal", "title": "Period"}},
          {{"field": "METRIC_NAME", "type": "quantitative", "title": "Value", "format": ",.2f"}}
        ]
      }}
    }}
  ]
}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIE CHART - COLORFUL VERSION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "mark": {{
    "type": "arc",
    "innerRadius": 0,
    "outerRadius": 120
  }},
  "encoding": {{
    "theta": {{
      "field": "value",
      "type": "quantitative",
      "aggregate": "sum",
      "stack": true
    }},
    "color": {{
      "field": "label",
      "type": "nominal",
      "legend": {{"title": "Account"}},
      "scale": {{"scheme": "category20b"}}
    }},
    "tooltip": [
      {{"field": "label", "type": "nominal", "title": "Account"}},
      {{"field": "value", "type": "quantitative", "title": "Amount", "format": ",.2f"}}
    ]
  }},
  "view": {{"stroke": null}}
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COLOR SCHEMES TO USE (pick based on chart):
- "category10" - 10 distinct colors (default, good for most cases)
- "category20" - 20 distinct colors (for many categories)
- "category20b" - Alternative 20 colors (warmer tones)
- "category20c" - Alternative 20 colors (cooler tones)
- "tableau10" - Tableau's color palette
- "tableau20" - Tableau's extended palette
- "set1" - ColorBrewer Set1 (bold colors)
- "set2" - ColorBrewer Set2 (pastel colors)
- "set3" - ColorBrewer Set3 (lighter colors)

CRITICAL RULES FOR COLORFUL GRAPHS:

1. BAR CHARTS:
   ✓ Use "color" encoding with "label" field
   ✓ Add legend with meaningful title
   ✓ Use "scheme": "category20" or "tableau20"

2. LINE CHARTS:
   ✓ Use colored points and thick lines
   ✓ Color by category if multiple lines
   ✓ If single line, color by label for each point

3. PIE CHARTS:
   ✓ ALWAYS color by "label"
   ✓ Use "category20b" or "set3" for variety
   ✓ Include legend for slice identification

4. LEGEND TITLES:
   - Balance Sheet → "Account"
   - Stock Summary → "Item"
   - Sales Register → "Customer" or "Product"
   - Cash Flow → "Category"
   - Profit & Loss → "Account"
   - Generic → "Category" or "Label"

5. AXIS TITLES:
   - X-axis: "Month", "Period", "Category", "Item"
   - Y-axis: "Amount (₹)", "Value (₹)", "Quantity"

FIELD MAPPING INTELLIGENCE:
- If query mentions "outflow" → use "outflow" field ONLY
- If query mentions "sales" → use "credit" or "value" field
- If query mentions "compare inflow vs outflow" → use BOTH "inflow" and "outflow"
- If query mentions "monthly" → x-axis should be months
- Use "label" for x-axis (months/items)
- Use proper Vega-Lite v5 schema

OUTPUT FORMAT:
Return ONLY valid JSON, no markdown, no explanation, no code blocks.
{{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "mark": ...,
  "encoding": {{...}},
  "transform": [...] (if needed)
}}

The spec should be COLORFUL, have LEGEND, and clear TOOLTIPS.
"""
    try:
        response = _LLM.invoke(prompt)
        spec_text = response.content.strip()
        
        # Remove markdown code fences if present
        if spec_text.startswith("```"):
            spec_text = spec_text.split("```")[1]
            if spec_text.startswith("json"):
                spec_text = spec_text[4:]
            spec_text = spec_text.strip()
        
        spec = json.loads(spec_text)
        
        # Validate basic structure
        if "$schema" in spec and "encoding" in spec:
            # Add the actual data
            spec["data"] = {"values": rows}
            
            # ========== ENFORCE COLORS IF MISSING ==========
            if "color" not in spec.get("encoding", {}):
                print("LLM forgot colors - adding default color scheme")
                spec["encoding"]["color"] = {
                    "field": "label",
                    "type": "nominal",
                    "legend": {"title": "Category"},
                    "scale": {"scheme": "category20"}
                }
            # ================================================
            
            return spec
        
        return None
        
    except Exception as e:
        print(f"LLM Vega generation failed: {e}")
        return None
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
    # ===== BILLS RECEIVABLE: PARTY-WISE COUNT =====
    if cmd.report_name == "Bills Receivable":

        party_count = {}

        for r in rows:
            label = r.get("label")
            if not label:
                continue

            party_count[label] = party_count.get(label, 0) + 1

        # Replace rows with aggregated rows (GRAPH ONLY)
        rows = [
            {
                "label": party,
                "value": count
            }
            for party, count in party_count.items()
        ]

        # Sort for better graph readability
        rows.sort(key=lambda x: x["value"], reverse=True)
        rows = rows[:20]
# =============================================

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
    vega_spec = None
    
    # Try LLM-based generation first
    vega_spec = generate_vega_spec_with_llm(
        rows=rows,
        user_query=user_query,
        chart_type=cmd.chart_type,
        numeric_fields=numeric_fields
    )
    
    # Fallback to deterministic generation
    if not vega_spec:
        print("Using deterministic Vega generation (LLM failed)")
        
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