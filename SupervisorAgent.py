import json  
import re
import os
import ast
from datetime import datetime
from typing import Optional
from graph_agent import run_table_pipeline
from tools.report_lookup import lookup_tally_report

# Import Memory
from langchain.memory import ConversationBufferMemory

from langchain.agents import Tool, AgentExecutor
from langchain.prompts import PromptTemplate
try:
    from langchain.agents import create_react_agent
    CREATE_REACT_AVAILABLE = True
except ImportError:
    CREATE_REACT_AVAILABLE = False
    from langchain.agents import initialize_agent, AgentType

from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.base import BaseCallbackHandler
from langchain_google_genai import ChatGoogleGenerativeAI

# Import your agents
try:
    from agents import TallyWorkerAgent, SummarizerAgent
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from agents import TallyWorkerAgent, SummarizerAgent

# Graph agent NL pipeline (natural language -> graph pipeline)
try:
    from graph_agent import run_nl_graph_pipeline
except ImportError:
    run_nl_graph_pipeline = None  

# ---------- OUTPUT / INTENT GUARD HELPERS (ENHANCED) ----------

def is_table_request(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in [
        "table",
        "tabular",
        "show it in a table",
        "show in table"
    ])

def is_rank_one_question(question: str) -> bool:
    """
    Detect single-value superlative questions (costliest, highest, cheapest, etc.)
    Returns True ONLY if asking for ONE item, not top N
    """
    q = question.lower()
    
    # Must have superlative keyword
    has_superlative = any(k in q for k in [
        "costliest", "most expensive", "highest", "maximum", "max",
        "cheapest", "lowest", "minimum", "min", "least expensive"
    ])
    
    if not has_superlative:
        return False
    
    # Must NOT have multi-item indicators
    has_multi_indicator = any(k in q for k in [
        "top", "compare", "graph", "plot", "chart", "list",
        "top 5", "top 3", "top 10", "top five", "top three"
    ])
    
    if has_multi_indicator:
        return False
    
    # Additional check: if "top N" pattern exists, return False
    if re.search(r'\btop\s+\d+', q):
        return False
    
    return True


def is_top_n_question(question: str) -> bool:
    """
    Detect "top N" questions that should return TABLE
    Examples: "top 5 items", "show top 3 expenses"
    """
    q = question.lower()
    
    # Pattern 1: "top N" where N is a number
    if re.search(r'\btop\s+\d+', q):
        return True
    
    # Pattern 2: "top five", "top ten" (spelled out)
    if re.search(r'\btop\s+(five|ten|three|four|six|seven|eight|nine)', q):
        return True
    
    # Pattern 3: just "top" with list/show context
    if 'top' in q and any(k in q for k in ['show', 'list', 'give', 'display']):
        return True
    
    return False


def is_simple_comparison(question: str) -> bool:
    """
    Detect simple binary/value comparison questions
    Examples: "Which is more: Assets or Liabilities?"
    Returns True if comparison is simple (2 items or abstract)
    """
    q = question.lower()
    
    # Must have comparison keywords
    has_comparison = any(k in q for k in [
        "which is more", "which is higher", "which is greater",
        "compare", "vs", "versus", "or", "difference between"
    ])
    
    if not has_comparison:
        return False
    
    # If user explicitly says "plot", "graph", "chart" → NOT simple
    if any(k in q for k in ["plot", "graph", "chart", "visualize"]):
        return False
    
    # Count comma-separated items (heuristic for multi-item)
    items = q.split(',')
    if len(items) > 2:
        return False  # More than 2 items = GRAPH
    
    # If "and" appears multiple times, likely multi-item
    and_count = q.count(' and ')
    if and_count > 1:
        return False
    
    return True


def is_multi_item_graph_request(question: str) -> bool:
    """
    Detect explicit multi-item requests that need GRAPH
    Examples: "Show me Cash, Bank, and Debtors"
    """
    q = question.lower()
    
    # Must have visual/analysis keywords
    has_visual = any(k in q for k in [
        "show", "plot", "graph", "chart", "visualize", 
        "compare", "analysis", "analyze", "breakdown"
    ])
    
    if not has_visual:
        return False
    
    # Count comma-separated items
    items = q.split(',')
    if len(items) >= 3:
        return True
    
    # Check for multiple "and" (e.g., "A and B and C")
    and_count = q.count(' and ')
    if and_count >= 2:
        return True
    
    return False


TALLY_AGENT = TallyWorkerAgent()
SUMMARIZER_AGENT = SummarizerAgent()

# ---------- Helper for Robust Parsing ----------
def parse_mixed_input(input_str: str) -> dict:
    """
    Tries to parse input as JSON first, then as a Python dict (single quotes).
    """
    if not input_str:
        return {}

    # 1. Try Standard JSON
    try:
        return json.loads(input_str)
    except Exception:
        pass

    # 2. Try Python Literal (handles single quotes)
    try:
        val = ast.literal_eval(input_str)
        if isinstance(val, dict):
            return val
    except Exception:
        pass

    return {}

# ---------- Tool Definitions ----------
def tool_fetch_companies(_input: str = "") -> str:
    try:
        companies = TALLY_AGENT.fetch_companies()
        return json.dumps({"status": "ok", "companies": companies}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def tool_list_companies_text(_input: str = "") -> str:
    try:
        companies = TALLY_AGENT.fetch_companies()
        if not companies:
            return "No companies found."
        lines = []
        for i, c in enumerate(companies):
            name = c.get("name", "<unknown>")
            lines.append(f"{i+1}. {name}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing companies: {e}"

def tool_fetch_report(input_str: str = "") -> str:
    """
    Fetch a raw Tally report for a given company and report name.

    Input: JSON string that decodes to an object with keys:
      - "report_name": the Tally report name, e.g. "Balance Sheet", "Stock Summary", "Day Book", "P&L"
      - "company": (OPTIONAL) - if not provided, uses active company from supervisor

    Output:
      {"status": "ok", "report": "<string or JSON of report>"}
      or {"status": "error", "error": "..."}.
    """
    try:
        payload = parse_mixed_input(input_str)

        # ========== CRITICAL FIX: USE ACTIVE COMPANY ==========
        company = _SUPERVISOR_SINGLETON.get_active_company()
        
        if not company:
            return json.dumps(
                {"status": "error", "error": "No company selected. Please select a company first."},
                ensure_ascii=False,
            )
        
        # Convert to dict format for TALLY_AGENT
        if isinstance(company, str):
            company = {
                "name": company,
                "id": company
            }
        # =======================================================

        report_name = payload.get("report_name")
        if not report_name:
            return json.dumps(
                {"status": "error", "error": "Missing report_name"},
                ensure_ascii=False,
            )

        rn = report_name.strip().lower()

        if rn in [
            "p&l",
            "pl",
            "profit & loss",
            "profit and loss",
            "profit & loss a/c",
            "trading and profit & loss",
            "trading & profit & loss",
        ]:
            report_name = "ProfitAndLoss"

        raw = TALLY_AGENT.fetch_report(company, report_name)
        if not raw:
            return json.dumps({"status": "error", "error": "empty report"})
        return json.dumps({"status": "ok", "report": raw}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def tool_summarize_report(input_str: str = "") -> str:
    """
    Summarize a report text with intelligent date/time filtering.

    Input: JSON string that decodes to an object with:
      - "raw": the report text / XML / JSON string
      - "metadata": {
          "user_query": "<original user question>",  # ← CRITICAL
          "report_name": "<report name>"
        }

    Output:
      {"status": "ok", "summary": "<summary text>"}
      or {"status": "error", "error": "..."}.
    """
    try:
        payload = parse_mixed_input(input_str)

        # If payload is empty but input_str wasn't, maybe the agent sent just raw text?
        if not payload and input_str and not input_str.strip().startswith("{"):
            payload = {"raw": input_str}

        raw = payload.get("raw") or ""
        metadata = payload.get("metadata", {})

        if not raw:
            return json.dumps({"status": "error", "error": "no raw content"})

        # ============ CRITICAL: PASS USER QUERY TO SUMMARIZER ============
        # If metadata doesn't have user_query, try to get it from supervisor
        if not metadata.get("user_query"):
            if hasattr(_SUPERVISOR_SINGLETON, 'current_user_query'):
                metadata["user_query"] = _SUPERVISOR_SINGLETON.current_user_query
        # ==================================================================

        summary = SUMMARIZER_AGENT.summarize(raw, metadata=metadata)
        return json.dumps({"status": "ok", "summary": summary}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    

# ---------- Graph insights tool (calls graph_agent pipeline) ----------
def tool_graph_insights(input_str: str = "") -> str:
    """
    Use this tool when the user asks for:
      - charts/graphs/visualizations
      - analysis of stock items based on quantities or rates
      - comparisons (e.g., compare particulars by Debit Amount)
      - analysis of Balance Sheet or assets vs liabilities

    Input: JSON string that decodes to an object with:
      - "company": dict or string (company name)
      - "question": the user's analytics / graph question
      - "static_vars": optional dict (e.g. date filters)

    This calls run_nl_graph_pipeline(question, company_name, static_vars) and returns:

      {
        "status": "ok",
        "summary_hint": {
          "question": "...",
          "company_name": "...",
          "graph_command": "...",
          "top_item": {...} | null,
          "row_count": int,
          "has_numeric_values": has_numeric,
,
          "numeric_row_count": int
        },
        "vega_spec": {...},
        "normalized_sample": {...}
      }
    """
    if run_nl_graph_pipeline is None:
        return json.dumps(
            {
                "status": "error",
                "error": "run_nl_graph_pipeline not available (graph_agent import failed)",
            },
            ensure_ascii=False,
        )
   


    try:
        
        payload = parse_mixed_input(input_str)
        company = _SUPERVISOR_SINGLETON.get_active_company()
        question = payload.get("question") or payload.get("query")
        # ------------------ PRESERVE 'ONLY' SEMANTICS (CRITICAL FIX) ------------------
        original_question = question

        # If user explicitly used "only", DO NOT let supervisor rewrite it
        if original_question and "only" in original_question.lower():
            question = original_question

        if not question:
            return json.dumps(
                {"status": "error", "error": "Missing question"},
                ensure_ascii=False,
            )

        q = question.lower()

        if not company:
            return json.dumps(
        {"status": "error", "error": "No company selected"},
        ensure_ascii=False,
    )

        # --------- FORCE REPORT SELECTION FOR STOCK QUERIES ---------

        #if any(k in q for k in ["stock", "stocks", "inventory", "items"]):
            # Override report inference
            #question = f"{question} from stock summary"

        if not question:
          return json.dumps(
        {"status": "error", "error": "Missing question"},
        ensure_ascii=False,
    )

                # --------- TABLE REQUEST GUARD (ADD) ---------
        if is_table_request(question):
          return json.dumps(
            {
                "status": "skipped",
                "output_type": "table",
                "reason": "User requested table output"
            },
            ensure_ascii=False,
        )


        static_vars = payload.get("static_vars")

        # company can be dict or string
        if isinstance(company, dict):
            company_name = company.get("name") or company.get("id")
        else:
            company_name = company

        if not company_name or not question:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Missing 'company' or 'question'. Received: {input_str}",
                },
                ensure_ascii=False,
            )
    
        out = run_nl_graph_pipeline(
        question=question,
        company_name=company_name,
        static_vars=static_vars,
        )


        normalized = out.get("normalized", {}) or {}
        rows = normalized.get("rows", []) or []

        # --------- PIE CHART NEGATIVE VALUE HANDLING ---------
        chart_type = out.get("generated_plot_command", "").lower()
        pie_rows = []
       
        if "pie" in chart_type:
          

         for r in rows:
            v = r.get("value")
            try:
                val = float(v)
            except Exception:
                continue

            if val == 0:
                continue

            pie_rows.append({
                "label": r.get("label"),
                "value": abs(val),  #  magnitude for pie
                "sign": "Negative" if val < 0 else "Positive"
            })

         rows = pie_rows

        # --------- detect numeric values safely ---------
        import math

        value_rows = []
        for r in rows:
            val = r.get("value")
            try:
                value_rows.append((r, float(val)))
            except Exception:
                continue

        has_numeric = len(value_rows) > 0

        top_item = None
        if has_numeric:
            top_item = max(value_rows, key=lambda t: t[1])[0]


        summary_hint = {
            "question": question,
            "company_name": company_name,
            "graph_command": out.get("generated_plot_command"),
            "top_item": top_item,
            "row_count": len(rows),
            "has_numeric_values": True,
            "numeric_row_count": len(value_rows),
        }

        normalized_sample = {
            "columns": normalized.get("columns", []),
            "rows": rows[:20],
        }

        vega_spec = out.get("vega_spec")

        if not vega_spec:
            vega_spec = None

        chart_cmd = out.get("generated_plot_command", "").lower()
        if vega_spec and "pie" in chart_cmd:
            # Force correct Vega-Lite pie spec
            vega_spec = {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {
                    "values": rows  # ← already abs(value) + sign
                },
                "mark": {
                    "type": "arc",
                    "innerRadius": 0
                },
                "encoding": {
                    "theta": {
                        "field": "value",
                        "type": "quantitative",
                        "aggregate": "sum"   #  REQUIRED
                    },
                    "color": {
                        "field": "label",
                        "type": "nominal",
                        "legend": {"title": "Account"}
                    },
                    "tooltip": [
                        {"field": "label", "type": "nominal"},
                        {"field": "value", "type": "quantitative"},
                        {"field": "sign", "type": "nominal"}
                    ]
                },
                "view": {
                    "stroke": None  #  REQUIRED FOR ARC IN STREAMLIT
                }
            }


# ==========================================================
        result = {
            "status": "ok",
            "summary_hint": summary_hint,
            "vega_spec": vega_spec,
            "normalized_sample": normalized_sample,
        }
        result["_force_final_answer_prefix"] = True
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps(
            {"status": "error", "error": str(e)},
            ensure_ascii=False,
        )

# ---------- Tool list ----------
TOOLS = [
    Tool(
        name="fetch_companies",
        func=tool_fetch_companies,
        description="Fetch list of companies. Returns JSON with status and a list of company dicts.",
    ),
    Tool(
        name="list_companies_text",
        func=tool_list_companies_text,
        description="Get a readable numbered list of companies.",
    ),
    Tool(
        name="lookup_tally_report",
        func=lookup_tally_report,
        description=(
            "CRITICAL: Call this tool EXACTLY ONCE per user query.\n\n"
        
        "PURPOSE: Find the correct Tally report name using semantic search.\n\n"
        
        "INPUT: The COMPLETE user question (copy-paste entire question)\n"
        "OUTPUT: Exact Tally report name to use\n\n"
        
        "EXAMPLES:\n"
        "CORRECT:\n"
        "  Input: 'Show daily sales value for April 2025'\n"
        "  Output: 'Sales Register'\n"
        "  [Then use Sales Register for ALL subsequent actions]\n\n"
        
        "CORRECT:\n"
        "  Input: 'What is my closing stock quantity per month?'\n"
        "  Output: 'Stock Summary'\n"
        "  [Then use Stock Summary - do NOT lookup again]\n\n"
        
        "WRONG:\n"
        "  Calling lookup_tally_report multiple times for same query\n"
        "  Trying different phrasings to get 'better' result\n"
        "  Calling lookup for parts of the question separately\n\n"
        
        "IRON RULE:\n"
        "Once you call this tool and get a result, that is THE report.\n"
        "Do NOT call this tool again in the same turn.\n"
        "Trust the first result absolutely.\n"
        ),
    ),
    Tool(
        name="fetch_report",
        func=tool_fetch_report,
        description=(
            "Fetch a raw Tally report for the currently selected company.\n\n"
            
            "IMPORTANT: Company is automatically provided by the system.\n"
            "DO NOT include company parameter in your input.\n\n"
            
            "Input: JSON string with report_name key only\n"
            
            "Example inputs:\n"
            '  {{"report_name": "Stock Summary"}}\n'
            '  {{"report_name": "Profit & Loss"}}\n'
            '  {{"report_name": "Day Book"}}\n\n'
            
            "Output: JSON with status and report.\n"
    ),
),
        
    Tool(
        name="summarize_report",
        func=tool_summarize_report,
        description=(
            "Summarize report text. Input must be JSON (as a string) that decodes to an object with key 'raw'. "
            "Output JSON has 'status' and 'summary'."
        ),
    ),
    Tool(
        name="graph_insights",
        func=tool_graph_insights,
        description=(
            "Generate analytical graphs and visual comparisons from Tally reports.\n\n"

        "USE THIS TOOL ONLY WHEN:\n"
        "- The user asks for analysis, comparison, trends, or visualization\n"
        "- The user explicitly asks for charts/graphs\n"
        "- The question involves comparing multiple items, groups, or values\n\n"

        "DO NOT USE THIS TOOL WHEN:\n"
        "- The user asks for a single numeric value (e.g. 'What is the value of capital account?')\n"
        "- The user asks single-item superlative questions (e.g. 'What is my costliest item?')\n"
        "- The user only selects a company\n"
        "- The user explicitly asks for table output\n"
        "- The user asks 'top N' questions (e.g. 'show top 5 items') - these should be TABLE\n\n"

        "INPUT:\n"
        "{\n"
        '  "question": "<user analytics / graph question>"\n'
        "}\n"
        "IMPORTANT:"
           "- Company context is provided by backend"
           "- NEVER ask the user to select a company"
           "- If no company is available, return an error and STOP\n\n"

        "OUTPUT (JSON):\n"
        "- On success: returns an object containing:\n"
        "    - summary_hint (metadata about numeric availability)\n"
        "    - vega_spec (Vega-Lite JSON for rendering the graph)\n"
        "    - normalized_sample (sample of normalized data)\n\n"
        "- On skip (no graph needed): returns:\n"
        "    { \"status\": \"skipped\", \"reason\": \"...\" }\n\n"

        "IMPORTANT:\n"
        "- Do NOT assume a graph will always be produced\n"
        "- Respect user intent (partial vs full graph) strictly\n"
    ),
),

]

# ---------- Callback Handler ----------
class TranscriptStreamingHandler(BaseCallbackHandler):
    def __init__(self, writer=None):
        super().__init__()
        self._writer = writer
        self._write_enabled = callable(writer)

    def _write(self, text: str):
        if self._write_enabled:
            try:
                self._writer(text + "\n")
            except Exception:
                pass

    def on_llm_new_token(self, token: str, **kwargs):
        print(token, end="", flush=True)
        self._write(token)
    
# ---------- The Main Class ----------
class SupervisorAgent:
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.0,
        transcripts_dir: str = "transcripts",
    ):
        # ---- ACTIVE COMPANY STATE ----
        self.active_company: Optional[str] = None
        self.current_user_query: Optional[str] = None
        self.lookup_called: bool = False

        # Default model
        self.model_name = model_name or os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"
        self.temperature = temperature
        self.transcripts_dir = transcripts_dir

        os.makedirs(self.transcripts_dir, exist_ok=True)
        self.ts_file = datetime.utcnow().strftime("transcript_%Y%m%dT%H%M%SZ.log")
        self.ts_path = os.path.join(self.transcripts_dir, self.ts_file)
        self.log_file = open(self.ts_path, "a", encoding="utf-8")

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key not found in .env")

        self.llm = ChatGoogleGenerativeAI(
            model=self.model_name,
            temperature=self.temperature,
            google_api_key=api_key,
            max_retries=0,
        )

        self.cb_manager = CallbackManager([TranscriptStreamingHandler(self._writer)])

        self.memory = ConversationBufferMemory(
            memory_key="chat_history", return_messages=True
        )


        # Prompt
        react_template ="""Answer the following questions as best you can.
        
You have access to the following tools:
{tools}

You are a SUPERVISOR over these tools. Your job is to:
- Understand the user's question.
- Decide whether they want a GRAPH (visual analysis / comparison) or just a VALUE/TEXT summary.
- Use lookup_tally_report tool to find the correct Tally report name.
- Call the right tools in the right order.
- Then give a clean final answer.

IMPORTANT: THINK STEP BY STEP IN YOUR "Thought" SECTION.

------------------ COMPANY SELECTION BEHAVIOUR ------------------
If the user asks to list companies:
- Call list_companies_text and return exactly its output

Company selection is handled externally. 
Do NOT repeat company confirmations unless explicitly asked.

You must handle company selection VERY carefully:

- If the user says things like:
    "use [Company Name]"
    "select [Company Name] as my company"
    "set company to [Company Name]"
    "switch to [Company Name]"
    "from now on, use [Company Name]"
    "change company to [Company Name]"
  and they do NOT ask any numeric / analysis question in the same message,
  then this is ONLY a company selection.

In that case:
  - DO NOT call fetch_report, summarize_report, or graph_insights.
  - In your Thought, note that the current company is now that name.
  - In your Final Answer, just confirm, e.g.:
        "Okay, I will use [Company Name] for further questions."
  - Then STOP.

You should use the latest company explicitly selected by the user
when you later call tools that require a company.

If the user asks a question that already contains a clear company name
(e.g. "Analyse my balance sheet for [Company Name]"),
you may use that name directly without asking again.

If a tool returns a list or data (e.g., company list),
you MUST return the tool output exactly as-is.
Do NOT summarize or describe the action.

------------------ INTENT CLASSIFICATION ------------------

In your Thought, ALWAYS classify the user query as one of:

  (A) VALUE: user wants one or a few numeric values.
      EXAMPLES:
      - "What is the value of capital account?"
      - "How much are my fixed assets?"
      - "What is my costliest stock item?" ← SINGLE ITEM SUPERLATIVE = VALUE
      - "Which item has the highest rate?" ← SINGLE ITEM = VALUE
      - "Show me the most expensive asset" ← SINGLE ITEM = VALUE
      - "What is the cheapest inventory item?" ← SINGLE ITEM = VALUE

  (B) SUMMARY: user wants a textual explanation of one report.

  (C) TABLE: user wants tabular output (list/table format).
      EXAMPLES:
      - "Show top 5 costliest items" ← TOP N = TABLE
      - "List top 3 expenses" ← TOP N = TABLE
      - "Give me top 10 stock items by rate" ← TOP N = TABLE
      - "Show me all items in a table"

  (D) ANALYSIS / COMPARISON (GRAPH): user wants visual comparison of MULTIPLE items.
      EXAMPLES:
      - "Compare Cash, Bank, and Debtors" ← MULTIPLE ITEMS = GRAPH
      - "Plot Capital Account and Loans" ← MULTIPLE ITEMS = GRAPH
      - "Analyze my stock items based on quantities" ← ANALYSIS = GRAPH
      - "Give me a breakdown of expenses" ← ANALYSIS = GRAPH

  (E) SIMPLE COMPARISON (VALUE): user wants simple answer comparing 2 things.
      EXAMPLES:
      - "Which is more: Assets or Liabilities?" ← BINARY = VALUE
      - "Compare Cash vs Bank balance" (if no plot/chart requested) ← VALUE

  (F) COMPANY_SELECTION: user only wants to set or change the current company,
      with no analytical question.

Use the meaning of the question, not exact wording.

KEY DISTINCTION RULES:
- Single item superlatives (costliest ONE item) → VALUE
- Top N items (top 5) → TABLE
- Multiple items comparison → GRAPH
- Binary comparison without graph request → VALUE
- Binary comparison WITH graph/plot request → GRAPH

If intent is COMPANY_SELECTION:
  - Follow the rules above and DO NOT call any tools.

If the user asks for a TABLE:
- Do NOT call any LLM for formatting
- The API layer will handle table rendering using Markdown
- Simply fetch the report if needed

When the user says "only X, Y, Z":
- Treat X,Y,Z as MANDATORY.
- If the report is Balance Sheet, NEVER drop a requested item.
- If an item is missing at leaf level, assume it exists as a parent group.

------------------ REPORT SELECTION RULES (RAG-POWERED) ------------------
------------------ REPORT SELECTION RULES (RAG-POWERED) ------------------

CRITICAL WORKFLOW - FOLLOW EXACTLY:

1. User asks a question (e.g., "Show daily sales for April 2025")
2. You MUST call lookup_tally_report EXACTLY ONCE with the user's FULL question
3. The tool returns ONE report name (e.g., "Sales Register")
4. You MUST use ONLY that report name for ALL subsequent actions
5. DO NOT call lookup_tally_report again in the same conversation turn

IRON RULE: ONE QUESTION = ONE LOOKUP = ONE REPORT

EXAMPLE FLOW (CORRECT):
User: "Show daily sales value for April 2025"
Thought: I need to find which report to use for sales data
Action: lookup_tally_report
Action Input: Show daily sales value for April 2025
Observation: Sales Register
Thought: The lookup returned Sales Register, I will use ONLY this report
Action: graph_insights
Action Input: {{"question": "Show daily sales value for April 2025"}}
[DONE - Do NOT call lookup_tally_report again]

WRONG FLOW (DO NOT DO THIS):
User: "Show daily sales value for April 2025"
Action: lookup_tally_report
Action Input: Show daily sales
Observation: Stock Summary
Action: lookup_tally_report   WRONG - Already called once
Action Input: sales register
Observation: Sales Register
Action: lookup_tally_report   WRONG - Called third time
[This is ERROR - violates ONE LOOKUP rule]

STRICT RULES:
1. Call lookup_tally_report ONLY ONCE per user query
2. Use the FIRST result returned - do NOT second-guess it
3. Do NOT try alternative phrasings or retry lookups
4. Do NOT call lookup for different parts of the same question
5. Trust the RAG system - it has semantic understanding

IF THE LOOKUP RETURNS WRONG REPORT:
- Still use it (the user can rephrase if needed)
- Do NOT attempt multiple lookups to "find better match"
- The lookup tool is already optimized for accuracy

REMEMBER:
- ONE user question = ONE lookup call = ONE report name
- Multiple lookups = confusion and wrong answers
- Trust the first lookup result absolutely

------------------ GRAPH vs TEXT vs TABLE BEHAVIOUR ------------------

CRITICAL DECISION TREE:

1. SINGLE-ITEM SUPERLATIVE (costliest, highest, cheapest ONE item):
   → Intent: VALUE
   → Tools: lookup_tally_report → fetch_report → summarize_report
   → Output: Plain text with the answer
   → DO NOT call graph_insights

2. TOP N QUESTIONS (top 5, top 3, etc.):
   → Intent: TABLE
   → Tools: lookup_tally_report → fetch_report
   → Output: Table format
   → DO NOT call graph_insights

3. SIMPLE BINARY COMPARISON (no graph/plot keyword):
   → Intent: VALUE
   → Tools: lookup_tally_report → fetch_report → summarize_report
   → Output: Plain text comparison
   → DO NOT call graph_insights

4. MULTI-ITEM COMPARISON or EXPLICIT GRAPH REQUEST:
   → Intent: GRAPH
   → Tools: graph_insights
   → Output: GRAPH_SPEC_JSON

IMPORTANT BALANCE SHEET RULE (CRITICAL):

If the user asks to analyse, visualize, plot, or chart the Balance Sheet
WITHOUT explicitly naming sub-items (like Current Assets, Loans, etc.):

- DO NOT attempt to plot the top-level Balance Sheet headers.
- ALWAYS expand the Balance Sheet into major numeric groups:
    • Capital Account
    • Loans (Liability)
    • Current Liabilities
    • Current Assets
    • Fixed Assets
- Use these expanded groups for graph_insights.
- This rule OVERRIDES the generic graph behavior.

EXAMPLES THAT MUST LEAD TO GRAPH (use 'graph_insights'):

These are GRAPH-LIKE / ANALYSIS queries:

1) "Give me an analysis of my Stock items based on their quantities"
2) "Can you help me compare my stock items based on their rate?"
3) "Compare my particulars based on their Debit Amount"
4) "Analyse my balance sheet."
5) "Help me understand my current assets and liabilities."
6) "Show me a breakdown of expenses"
7) "Visualize my top items by value"
8) "Plot Cash, Bank, and Debtors" ← MULTIPLE items
9) "Compare Assets vs Liabilities with a chart"

In general, anything like:
- "Give me an analysis of ..."
- "Can you help me compare ..." (MULTIPLE items)
- "Compare ... based on ..." (MULTIPLE items)
- "Analyse my ..."
- "Help me understand my ... vs ..."
- "Show me a breakdown of ..."
- "Visualize ..."
- "Chart my ..."
or explicit mentions of "chart", "graph", "visualize", "based on quantities",
"based on rate", "compare by amount", "breakdown", "distribution"
SHOULD go to the tool named graph_insights.

EXAMPLES THAT MUST NOT LEAD TO GRAPH (VALUE / TEXT ONLY):

These are specific VALUE queries; NO graph:

1) "What is the value of my current loans?" ← SINGLE VALUE
2) "How much are my fixed assets worth?" ← SINGLE VALUE
3) "What's the value of my indirect incomes?" ← SINGLE VALUE
4) "What is my total revenue?" ← SINGLE VALUE
5) "How much cash do I have?" ← SINGLE VALUE
6) "What is my costliest stock item?" ← SINGLE ITEM SUPERLATIVE
7) "Which item has the highest rate?" ← SINGLE ITEM SUPERLATIVE
8) "Show me the cheapest inventory item" ← SINGLE ITEM SUPERLATIVE
9) "Which is more: Assets or Liabilities?" ← SIMPLE BINARY (no graph keyword)

In general, questions that start with phrases like:
- "What is the value of ..."
- "How much are my ..."
- "What's the value of ..."
- "What is the total of ..."
- "How much ..."
- "What is my ..."
- "What is my costliest/highest/cheapest [SINGLE ITEM]..."
- "Which is more: X or Y?" (without plot/graph)
and refer to a specific group or head in a report are VALUE questions → NO graph.

EXAMPLES THAT MUST LEAD TO TABLE:

1) "Show top 5 costliest items" ← TOP N
2) "List top 3 expenses" ← TOP N
3) "Give me top 10 stock items by rate" ← TOP N
4) "Display all items in a table" ← EXPLICIT TABLE

------------------ TOOL DECISION RULES ------------------

After you classify:

- If intent is COMPANY_SELECTION:
    * DO NOT use any tools.

- If intent is (A) VALUE:
    * DO NOT use graph_insights.
    * FIRST call lookup_tally_report with the user's question
    * THEN use fetch_report with the returned report_name
    * If needed, then use summarize_report on the report text to help extract the exact number.
    * Finally, answer in plain text with the numeric value and a brief explanation.

- If intent is (B) SUMMARY:
    * FIRST call lookup_tally_report
    * Then use fetch_report and summarize_report.
    * Answer with a textual explanation. No graph unless user explicitly asks.

- If intent is (C) TABLE:
    * FIRST call lookup_tally_report
    * Then use fetch_report with appropriate report_name.
    * DO NOT call graph_insights.
    * Return table output.

- If intent is (D) ANALYSIS / COMPARISON (GRAPH):
1. You MUST call lookup_tally_report with the user question
2. Use the EXACT report name returned
3. Call graph_insights with:
   - question
   - report_name
4. You MUST NOT guess or infer report names yourself

    * It also returns a flag summary_hint.has_numeric_values:
        - If has_numeric_values is true, you can describe highest/lowest items.
        - If has_numeric_values is false, then the data did NOT contain usable numeric values
          for that analysis (for example, all "value" fields are null or non-numeric).
          In that case, you MUST clearly say that no meaningful numeric comparison is possible
          and that the graph (if any) may not be informative. Do NOT claim any "highest" or "lowest" item.

- If intent is (E) SIMPLE COMPARISON (VALUE):
    * FIRST call lookup_tally_report
    * Then use fetch_report + summarize_report
    * Answer with plain text comparison
    * DO NOT use graph_insights

------------------ TOOL INPUT HINTS ------------------
CRITICAL: COMPANY CONTEXT IS AUTOMATICALLY PROVIDED

When calling tools follow these input patterns:

- lookup_tally_report:
    Input: Plain text user question
    Example: What is my closing stock?

- fetch_report:
    Input: JSON string with report_name key only
    Company is automatically provided by system

- summarize_report:
    Input: JSON string with raw key containing the report text
    CRITICAL: ALWAYS include user_query in metadata for date-aware extraction

- graph_insights:
    Input: JSON with question key only
    Company context is automatically provided

REMEMBER: 
- Company is already selected and managed by the system
- NEVER ask the user to select a company
- NEVER include company name in tool inputs

------------------ FINAL ANSWER FORMAT ------------------
When you are done:

- If you DID NOT use graph_insights:
    Finish EXACTLY as:
    Final Answer: [your text answer here]

- If you DID use graph_insights and you have vega_spec:
    YOU MUST format EXACTLY like this:
    
    Final Answer: [DETAILED BREAKDOWN - show month-wise/item-wise values from the data]
###GRAPH_SEPARATOR###
[VEGA_JSON_HERE]

CRITICAL RULES FOR GRAPH SUMMARIES:
1. Read the actual DATA from graph_insights response
2. SHOW month-by-month or item-by-item VALUES in your summary
3. DO NOT just mention highest/lowest - SHOW ALL MONTHS/ITEMS with values
4. Use bullet points (-) for each month/item with its value
5. Be SPECIFIC - include at least 5-10 data points

CRITICAL: Once you write "Final Answer:", STOP immediately and do NOT write anything else.
GOOD EXAMPLE (CORRECT):
Final Answer: Projected cash outflow breakdown:

- April: ₹93,60,000 (outflow)
- May: ₹60,52,000 (outflow)
- June: ₹50,54,000 (outflow)
- July: ₹56,48,000 (outflow)
- August: ₹44,84,000 (outflow)
- September: ₹32,82,000 (outflow)

Highest outflow in April at ₹93.6M.
###GRAPH_SEPARATOR###
[JSON]

BAD EXAMPLE (WRONG):
Final Answer: April has highest outflow at ₹93.6M.
###GRAPH_SEPARATOR###
[JSON]

REMEMBER: The summary should have MULTIPLE lines showing the actual breakdown!
------------------ GENERAL REACT FORMAT ------------------
FORMAT - FOLLOW EXACTLY:

You MUST follow this EXACT format for each step:

Thought: [your reasoning - ONE line only]
Action: [tool name - exactly one of {tool_names}]
Action Input: [valid JSON or plain text]
Observation: [will be provided by system]

CRITICAL RULES:
- Write ONLY ONE Thought per step
- IMMEDIATELY follow Thought with Action
- NEVER write multiple Thoughts in a row
- NEVER skip Action after Thought
- Stop when you have Final Answer
IMPORTANT: Never repeat the words "Thought:" or "Action:". Use them exactly once if required.

Current Chat History:
{chat_history}

Begin!

User Input: {input}
Thought:
{agent_scratchpad}
"""

        self.prompt = PromptTemplate(
    template=react_template,
    input_variables=["tools", "tool_names", "input", "chat_history", "agent_scratchpad"]
)

        if CREATE_REACT_AVAILABLE:
            agent = create_react_agent(llm=self.llm, tools=TOOLS, prompt=self.prompt)
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=TOOLS,
                verbose=True,
                callback_manager=self.cb_manager,
                handle_parsing_errors=True,
                memory=self.memory,
            )
        else:
            self.agent_executor = initialize_agent(
                tools=TOOLS,
                llm=self.llm,
                agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                callback_manager=self.cb_manager,
                handle_parsing_errors=True,
                memory=self.memory,
            )
   
    def _writer(self, line: str):
            try:
                self.log_file.write(line)
                self.log_file.flush()
            except Exception:
                pass
   

    def run_interactive(self):
        print(f"Transcript logging to: {self.ts_path}")

        print("\nInitializing Agent...\n")
        try:
            response = self.agent_executor.invoke(
                {
                    "input": "Start now. 1. List companies. 2. Ask user to select one. 3. Fetch and Summarize Report."
                }
            )
        except Exception as e:
            print(f"\nCRITICAL ERROR: {e}")
            return

        if isinstance(response, dict):
            final_output = response.get("output", "")
        else:
            final_output = str(response)

        print("\n=== AGENT RESPONSE ===\n", final_output)

        while "USER_PROMPT:" in final_output:
            try:
                prompt_text = final_output.split("USER_PROMPT:", 1)[1].strip()
            except Exception:
                prompt_text = "Input required:"

            user_input = input(f"\n{prompt_text}\n> ").strip()

            response = self.agent_executor.invoke({"input": user_input})

            if isinstance(response, dict):
                final_output = response.get("output", "")
            else:
                final_output = str(response)

            print("\n=== AGENT RESPONSE ===\n", final_output)

        self.log_file.close()
    def set_active_company(self, company_name: Optional[str]):
        if not company_name:
            return
        self.active_company = company_name.strip()


    def get_active_company(self) -> Optional[str]:
        return self.active_company
    
    def clean_agent_output(self, output: str) -> str:
        """
        Post-process agent output to remove trailing garbage after JSON.
        This is a safety net in case the agent adds extra text.
        """
        # HARD STOP: prevent ReAct from misreading graph summaries
        if output and "###GRAPH_SEPARATOR###" in output:
            if not output.strip().startswith("Final Answer:"):
                output = "Final Answer: " + output.strip()

        if "###GRAPH_SEPARATOR###" not in output:
            return output
        
        parts = output.split("###GRAPH_SEPARATOR###", 1)
        if len(parts) != 2:
            return output
        
        summary = parts[0].strip()
        json_part = parts[1].strip()
        
        # Find the last complete JSON object using brace counting
        brace_count = 0
        last_valid_pos = -1
        
        for i, char in enumerate(json_part):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    last_valid_pos = i
                    break  # Found complete JSON, stop here
        
        if last_valid_pos != -1:
            # Truncate everything after the last }
            json_part = json_part[:last_valid_pos + 1]
        
        return f"{summary}\n###GRAPH_SEPARATOR###\n{json_part}"

# ---------- Bootstrap single shared Supervisor + llm export ----------
try:
    _SUPERVISOR_SINGLETON = SupervisorAgent()
    llm = _SUPERVISOR_SINGLETON.llm
    agent_executor = _SUPERVISOR_SINGLETON.agent_executor
except Exception as _e:
    llm = None
    agent_executor = None

def is_company_list_request(q: str) -> bool:
     q = q.lower()
     return any(k in q for k in [
        "list companies",
        "show companies",
        "company list",
        "available companies",
        "show company",
        "list company"
    ])

def run_supervisor_query(query: str) -> dict:
    """
    Main entry point for supervisor queries with intelligent routing
    """
    if agent_executor is None:
        raise RuntimeError("SupervisorAgent not initialized")
    
    q = query.strip()
    _SUPERVISOR_SINGLETON.current_user_query = q
    # ==================== EARLY GUARDS (BEFORE AGENT CALL) ====================
    
    # Guard 1: Company list requests
    if is_company_list_request(q):
        text = tool_list_companies_text()
        return {
            "output_type": "text",
            "summary": text,
            "__stop__": True 
        }

    # Guard 2: Company selection (no query)
    if (
        re.fullmatch(r"[A-Za-z0-9 .&()\-]+", q)
        and len(q.split()) >= 2
        and ("pvt" in q.lower() or "ltd" in q.lower())
        and not any(k in q.lower() for k in [
            "show", "what", "plot", "compare", "graph",
            "analysis", "analyze", "chart", "table", "list"
        ])
    ):
        _SUPERVISOR_SINGLETON.set_active_company(q)
        return {
            "output_type": "text",
            "summary": f"Okay, I will use {q} for further questions."
        }

    # Guard 3: Single-item superlative questions (costliest, highest, etc.)
    if is_rank_one_question(q):
        # Let agent handle it BUT ensure it goes to VALUE path
        # Agent will use fetch_report + summarize_report
        result = agent_executor.invoke({"input": query})
        output = result.get("output", "")
        output = _SUPERVISOR_SINGLETON.clean_agent_output(output)
        
        # Force VALUE output (no graph)
        return {
            "output_type": "text",
            "summary": output
        }

    # Guard 4: Top N questions (should be TABLE)
    if is_top_n_question(q):
        company = _SUPERVISOR_SINGLETON.get_active_company()
        
        if not company:
            return {
                "output_type": "text",
                "summary": "Please select a company first."
            }
        
        return run_table_pipeline(
            question=query,
            company_name=company
        )

    # Guard 5: Simple comparison (should be VALUE)
    if is_simple_comparison(q):
        result = agent_executor.invoke({"input": query})
        output = result.get("output", "")
        output = _SUPERVISOR_SINGLETON.clean_agent_output(output)
        
        return {
            "output_type": "text",
            "summary": output
        }
    # ==================== AGENT PROCESSING ====================
    
    result = agent_executor.invoke({"input": query})
    output = result.get("output", "")
    output = _SUPERVISOR_SINGLETON.clean_agent_output(output)

    # ==================== POST-PROCESSING GUARDS ====================

    # Guard 6: Explicit table requests
    if is_table_request(q):
        company = _SUPERVISOR_SINGLETON.get_active_company()
        
        return run_table_pipeline(
            question=query,
            company_name=company or ""
        )

    # Guard 7: Graph output detection
    if "###GRAPH_SEPARATOR###" in output:
        try:
            parts = output.split("###GRAPH_SEPARATOR###", 1)
            summary_text = parts[0].strip()
            json_text = parts[1].strip()
            
            spec = json.loads(json_text)

            return {
                "output_type": "graph",
                "summary": summary_text,
                "vega_spec": spec
            }
        except Exception as e:
        # Fallback if parsing fails
            return {
            "output_type": "text",
            "summary": output
        }
    # Default: Text output
    return {
        "output_type": "text",
        "summary": output
    }
 

def get_supervisor():
    global _SUPERVISOR_SINGLETON
    if _SUPERVISOR_SINGLETON is None:
        _SUPERVISOR_SINGLETON = SupervisorAgent()
    return _SUPERVISOR_SINGLETON

_SUPERVISOR_SINGLETON = SupervisorAgent()