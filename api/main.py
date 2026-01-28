from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading
import json
import re
from typing import Optional


from SupervisorAgent import (
    SupervisorAgent,
    tool_list_companies_text,
    tool_fetch_companies,
    get_supervisor  
)
from graph_agent import run_table_pipeline

# Initialize after imports
_SUPERVISOR_SINGLETON = get_supervisor()

# ========== HARDCODED COMPANY (CRITICAL) ==========
HARDCODED_COMPANY = "Modi Chemplast Materials Pvt Ltd"
# ==================================================

app = FastAPI(
    title="Tally Agentic Pipeline API",
    version="1.0.0"
)

# ========== CORS MIDDLEWARE (CRITICAL FOR NGROK + REACT) ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ==================================================================

# Request/Response Models
class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    output_type: str
    summary: Optional[str] = None
    vega_spec: Optional[dict] = None


def clean_graph_output(raw_output: str) -> dict:
    """
    Clean agent output to prevent raw JSON in summary.
    Handles markdown code fences, trailing text, and brace counting.
    """
    if "###GRAPH_SEPARATOR###" not in raw_output:
        return {
            "output_type": "text",
            "summary": raw_output
        }
    
    try:
        parts = raw_output.split("###GRAPH_SEPARATOR###", 1)
        summary_text = parts[0]
    
         # Remove "Final Answer: " prefix if present
        if summary_text.startswith("Final Answer:"):
            summary_text = summary_text[len("Final Answer:"):].strip()
        
        # Strip only leading/trailing whitespace, NOT internal newlines
        summary_text = summary_text.strip()
        json_text = parts[1].strip()
        
        print(f"DEBUG: Raw json_text length: {len(json_text)} chars")
        print(f"DEBUG: json_text first 200 chars:\n{json_text[:200]}")
        
        # ========== CRITICAL: EXTRACT ONLY VALID JSON ==========
        # Find the first { and last matching }
        first_brace = json_text.find('{')
        if first_brace == -1:
            raise ValueError("No opening brace found in JSON")
        
        # Find matching closing brace by counting nested braces
        brace_count = 0
        last_brace = -1
        for i in range(first_brace, len(json_text)):
            if json_text[i] == '{':
                brace_count += 1
            elif json_text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    last_brace = i
                    break
        
        if last_brace == -1:
            raise ValueError("No matching closing brace found")
        
        # Extract ONLY the valid JSON portion (ignore everything after)
        json_text = json_text[first_brace:last_brace + 1]
        # ========================================================
        
        print(f"DEBUG: Extracted JSON length: {len(json_text)} chars")
        print(f"DEBUG: Extracted JSON first 200 chars:\n{json_text[:200]}")
        print(f"DEBUG: Extracted JSON last 100 chars:\n{json_text[-100:]}")
        
        # ========== Remove markdown code fences ==========
        if json_text.startswith("```"):
            print("Detected markdown code fence with backticks")
            fence_parts = json_text.split("```")
            if len(fence_parts) >= 3:
                json_text = fence_parts[1]
                if json_text.lower().startswith("json"):
                    json_text = json_text[4:]
                json_text = json_text.strip()
        
        # Remove any remaining backticks
        json_text = json_text.strip('`').strip()
        # =================================================
        
        # ========== Detect and fix raw JSON in summary ==========
        if summary_text.startswith('{') or '"status"' in summary_text or '"vega_spec"' in summary_text:
            print("Detected raw JSON in summary, converting to human-readable")
            try:
                full_json = json.loads(summary_text)
                vega_spec = full_json.get('vega_spec')
                summary_hint = full_json.get('summary_hint', {})

                normalized_sample = full_json.get('normalized_sample', {})
                rows = normalized_sample.get('rows', [])
                question = summary_hint.get('question', '')

                if rows and question:
                    # Generate smart summary with date awareness
                    summary_text = generate_smart_summary(
                        report_name="Analysis",
                        rows=rows,
                        user_query=question,
                        output_type="graph"
                    )
                else:
                    # Fallback to basic summary
                    top_item = summary_hint.get('top_item', {})
                    row_count = summary_hint.get('row_count', 0)
                    
                    if top_item:
                        label = top_item.get('label', 'Unknown')
                        value = top_item.get('value', 0)
                        summary_text = f"The analysis shows {row_count} items with {label} having the highest value at ₹{value:,.2f}."
                    else:
                        summary_text = f"The analysis shows {row_count} items in the visualization."
                
                # If json_text is still malformed, use vega_spec from parsed summary
                if vega_spec:
                    json_text = json.dumps(vega_spec, ensure_ascii=False)
                    print("✅ Used vega_spec from summary JSON")
                    
            except Exception as e:
                print(f"⚠️ Error parsing summary JSON: {e}")
                summary_text = "Graph visualization generated successfully."
        
        print(f"About to parse final JSON spec")
        spec = json.loads(json_text)
        print(f"Successfully parsed JSON spec, has $schema: {'$schema' in spec}")
        
        return {
            "output_type": "graph",
            "summary": summary_text,
            "vega_spec": spec
        }
        
    except json.JSONDecodeError as e:
        print(f"JSON DECODE ERROR: {e}")
        print(f"Problematic JSON text (first 500 chars):\n{json_text[:500] if 'json_text' in locals() else 'N/A'}")
        import traceback
        traceback.print_exc()
        return {
            "output_type": "text",
            "summary": f"Error: Invalid JSON in graph output. {str(e)}"
        }
    except Exception as e:
        print(f"ERROR in clean_graph_output: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "output_type": "text",
            "summary": f"Error processing graph output: {str(e)}"
        }
    
agent_lock = threading.Lock()

def clean_react_output(text: str) -> str:
    text = re.sub(r"Action:\s*\nAction Input:\s*", "", text)
    text = re.sub(r"Observation:\s*", "", text)
    return text.strip()  

def is_table_request(q: str) -> bool:
    q = q.lower()
    return any(k in q for k in [
        "table", "list", "show all", "rows",
        "top 5", "top 10", "top "
    ])

def table_to_markdown(columns: list, rows: list) -> str:
    if not columns or not rows:
        return "_No data available._"

    lines = []

    # header
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")

    # rows
    for row in rows:
        values = [str(row.get(col, "")) for col in columns]
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)

def generate_smart_summary(
    report_name: str, 
    rows: list, 
    user_query: str,
    output_type: str = "table"
) -> str:
    """
    Generate intelligent summary for GRAPH/TABLE outputs
    WITH month-wise/item-wise breakdown in summary text
    """
    if not rows:
        return "No data available to summarize."

    # Prepare sample data (limit to 20 rows for token efficiency)
    sample_rows = rows[:20]
    
    prompt = f"""
You are a financial data analyst.

USER QUERY: {user_query}
REPORT: {report_name}
OUTPUT TYPE: {output_type}

DATA (showing breakdown):
{json.dumps(sample_rows, ensure_ascii=False, indent=2)}

TASK:
Generate a summary that INCLUDES the actual breakdown from the data.

FORMAT RULES:
1. First line: Overview statement
2. Next lines: ACTUAL DATA BREAKDOWN (month-wise/item-wise/customer-wise)
3. Last line: Total or key insight

CRITICAL REQUIREMENTS:
- MUST include the actual values from the data
- For monthly data: Show month-by-month values
- For item-wise data: Show top items with values
- Use ₹ symbol for currency
- Use exact numbers from data (with commas for readability)
- Keep summary under 15 lines

SPECIAL CASE – BILLS RECEIVABLE / PAYABLE SUMMARY:

- If the report is Bills Receivable or Bills Payable:
  - Show ONLY the TOP 10 parties in the breakdown
  - Rank by absolute value (highest outstanding or count first)
  - Do NOT list all rows, even if more data is available

EXAMPLES:

Query: "Show projected cash outflow per month"
Data: [
  {{"label": "April", "value": 1245000}},
  {{"label": "May", "value": 1520000}},
  {{"label": "June", "value": 1830000}}
]
Summary:
"Projected cash outflow breakdown for FY 2024-25:

- April: ₹12,45,000
- May: ₹15,20,000
- June: ₹18,30,000
- July: ₹14,50,000
- August: ₹16,80,000

Total projected outflow: ₹78,75,000"

Query: "Show monthly sales for FY 2024-25"
Data: [
  {{"label": "Apr-2024", "credit": 2500000, "closing_balance": 2500000}},
  {{"label": "May-2024", "credit": 7000000, "closing_balance": 9500000}}
]
Summary:
"Monthly sales performance for FY 2024-25:

- Apr-2024: ₹25,00,000
- May-2024: ₹70,00,000
- Jun-2024: ₹41,60,000
- Jul-2024: ₹31,83,000
- Aug-2024: ₹56,02,000
- Sep-2024: ₹47,01,000
- Oct-2024: ₹1,68,690
- Nov-2024: ₹0
- Dec-2024: ₹50,30,000
- Jan-2025: ₹25,00,000

Highest sales in May-2024 at ₹70,00,000."

Query: "Compare stock items by value"
Data: [
  {{"label": "Item A", "value": 520000}},
  {{"label": "Item B", "value": 315000}},
  {{"label": "Item C", "value": 280000}}
]
Summary:
"Stock value comparison across items:

1. Item A: ₹5,20,000
2. Item B: ₹3,15,000
3. Item C: ₹2,80,000
4. Item D: ₹1,95,000
5. Item E: ₹1,50,000

Total stock value: ₹16,60,000"

Query: "Show customer-wise outstanding"
Data: [
  {{"label": "ABC Traders", "value": 520000}},
  {{"label": "XYZ Corp", "value": 315000}}
]
Summary:
"Outstanding amounts per customer:

- ABC Traders: ₹5,20,000
- XYZ Corp: ₹3,15,000
- DEF Industries: ₹2,80,000

Total outstanding: ₹11,15,000"

IMPORTANT RULES:
1. ALWAYS show the breakdown (month-wise/item-wise/customer-wise)
2. DO NOT just say "data shows X months" - SHOW the actual months
3. Use bullet points (-) for readability
4. Include totals where relevant
5. Highlight highest/lowest values
6. Format large numbers with commas (₹12,45,000)

STRUCTURED OUTPUT FORMAT (MANDATORY FOR ALL QUERIES, NO EXCEPTIONS):

Return the summary in the following structure exactly:

ANALYSIS SUMMARY:
(one short sentence explaining what the data represents)

MONTH-WISE / ITEM-WISE BREAKDOWN:
- Use one bullet per label
- Each bullet must be on a NEW LINE
- Format strictly as:
  - <Label>: ₹<Value>

KEY INSIGHT:
(one short line highlighting highest / lowest / trend)

ABSOLUTE FORMATTING CONSTRAINT (NON-NEGOTIABLE):
- DO NOT write long paragraphs
- DO NOT combine multiple months/items in one line
- ALWAYS put each value on a separate bullet line
- Use clear line breaks between sections
INVALID FORMAT (NEVER USE):
April: ₹X - May: ₹Y - June: ₹Z

VALID FORMAT (MUST FOLLOW):
- April: ₹X
- May: ₹Y
- June: ₹Z

NOW GENERATE SUMMARY WITH BREAKDOWN:
"""

    try:
        resp = _SUPERVISOR_SINGLETON.llm.invoke(prompt)
        summary = resp.content.strip()
        
        # Post-process: Ensure breakdown exists
        if len(summary.split('\n')) < 3:
            # Summary too short, force breakdown
            breakdown_lines = []
            for i, row in enumerate(sample_rows[:10]):
                label = row.get('label', f'Item {i+1}')
                value = row.get('value') or row.get('credit') or row.get('outflow') or row.get('closing_balance')
                
                if value is not None:
                    try:
                        value_num = float(value)
                        breakdown_lines.append(f"- {label}: ₹{value_num:,.2f}")
                    except:
                        breakdown_lines.append(f"- {label}: {value}")
            
            if breakdown_lines:
                summary = f"Data breakdown:\n\n" + "\n".join(breakdown_lines)
        
        return summary
        
    except Exception as e:
        print(f"LLM summary error: {e}")
        # Fallback: Generate basic breakdown
        breakdown_lines = [f"Data from {report_name}:\n"]
        
        for i, row in enumerate(sample_rows[:10]):
            label = row.get('label', f'Item {i+1}')
            value = row.get('value') or row.get('credit') or row.get('outflow') or row.get('closing_balance')
            
            if value is not None:
                try:
                    value_num = float(value)
                    breakdown_lines.append(f"- {label}: ₹{value_num:,.2f}")
                except:
                    breakdown_lines.append(f"- {label}: {value}")
        
        return "\n".join(breakdown_lines)

def extract_graph_from_intermediate_steps(result: dict):
    steps = result.get("intermediate_steps", [])
    for step in steps:
        if isinstance(step, tuple) and len(step) == 2:
            _action, observation = step
            if isinstance(observation, dict) and "vega_spec" in observation:
                return {
                    "vega_spec": observation["vega_spec"],
                    "summary": observation.get("summary", "Graph generated.")
                }
    return None

# ========== MAIN CHAT ENDPOINT ==========
@app.post("/chat")
def chat(req: ChatRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # ========== AUTOMATICALLY SET COMPANY ==========
    _SUPERVISOR_SINGLETON.set_active_company(HARDCODED_COMPANY)
    _SUPERVISOR_SINGLETON.current_user_query = req.query 
    print(f"Using company: {HARDCODED_COMPANY}")
    print(f"Query: {req.query}")
    # ===============================================

    # Table Request
    if is_table_request(req.query):
        try:
            print("Detected TABLE request")
            table = run_table_pipeline(
                question=req.query,
                company_name=HARDCODED_COMPANY
            )

            summary_llm = generate_smart_summary(
            report_name=table.get("report_used"),
            rows=table.get("rows"),
            user_query=req.query, 
            output_type="table"
        )

            markdown_table = table_to_markdown(
                table.get("columns", []),
                table.get("rows", [])
            )

            summary = (
    "### 📋 Table View\n\n"
    f"**Company:** {HARDCODED_COMPANY}\n\n"
    f"**Report:** {table.get('report_used')}\n\n"
    f"**Summary:**\n\n{summary_llm}\n\n"
    "---\n\n"       
    f"{markdown_table}"
)

            return ChatResponse(
                output_type="markdown",
                summary=summary
            )
        except Exception as e:
            print(f"Table error: {e}")
            return ChatResponse(
                output_type="text",
                summary=f"Error generating table: {str(e)}"
            )

    # Main Path: Supervisor
    with agent_lock:
        query = req.query
        ql = query.lower()
        
        # Hint for costliest queries
        if "costliest" in ql and any(k in ql for k in ["stock", "item", "inventory"]):
            query = query + " (consider costliest based on RATE, not total value or closing stock)"
        
        try:
            print("Invoking agent...")
            result = _SUPERVISOR_SINGLETON.agent_executor.invoke({"input": query})
            print("Agent completed")
        except Exception as e:
            print(f"Agent error: {e}")
            return ChatResponse(
                output_type="text",
                summary=f"Error processing query: {str(e)}"
            )

    # Handle tool-based graph output
    graph_payload = extract_graph_from_intermediate_steps(result)

    if graph_payload:
        print("Returning GRAPH from intermediate steps")
        vega_spec = graph_payload.get("vega_spec", {})
        rows = vega_spec.get("data", {}).get("values", [])
    
        smart_summary = generate_smart_summary(
        report_name="Analysis",
        rows=rows,
        user_query=req.query,  # ← User's original query
        output_type="graph"
    )
        return ChatResponse(
        output_type="graph",
        summary=smart_summary,  
        vega_spec=graph_payload["vega_spec"]
    )

    output = result.get("output") if isinstance(result, dict) else str(result)

# SAFETY GUARD
    if isinstance(output, str) and "###GRAPH_SEPARATOR###" in output:
        cleaned = clean_graph_output(output)
        return ChatResponse(**cleaned)

    # Normal text response
    output = clean_react_output(output)
    return ChatResponse(
        output_type="text",
        summary=output
)


# Health Check
@app.get("/")
def health():
    return {
        "status": "API running",
        "company": HARDCODED_COMPANY,
        "version": "1.0.0"
    }

@app.get("/company")
def get_company():
    return {
        "company_name": HARDCODED_COMPANY,
        "active": True
    }