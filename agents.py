import json
import logging
from typing import Any, Dict, List, Optional
import os
# Ensure these imports match your actual folder structure

from tools.tally_company_tool import get_company_list
from tools.tally_report_tool import get_report
from tools.summarize_tool import summarize_text


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class TallyWorkerAgent:
    """
    Worker agent responsible for interacting with Tally-related tools.
    """

    def __init__(self, *, retry: int = 1, timeout_seconds: Optional[int] = None):
        self.retry = max(1, int(retry))
        self.timeout_seconds = timeout_seconds

    def fetch_companies(self) -> List[Dict[str, Any]]:
        """Return list of company dicts."""
        last_exc = None
        for attempt in range(1, self.retry + 1):
            try:
                logger.info("TallyWorkerAgent: fetching company list (attempt %d/%d)", attempt, self.retry)
                
                
                company_names = get_company_list.invoke({})
                
                if isinstance(company_names, dict) and "error" in company_names:
                     raise Exception(company_names["error"])

                # Standardize output to list of dicts for the Supervisor
                result = []
                if isinstance(company_names, list):
                    for name in company_names:
                        result.append({"name": name, "id": name}) 
                return result

            except Exception as e:
                last_exc = e
                logger.exception("Error fetching companies on attempt %d: %s", attempt, e)
        raise last_exc

    def fetch_report(self, company: Dict[str, Any], report_name: str) -> str:
        """Fetch raw report XML/text for given company and report name."""
        if not company or not isinstance(company, dict):
            raise ValueError("company must be a dict")
        if not report_name:
            raise ValueError("report_name must be a string")

        # Extract the specific string name for the tool
        company_name_str = company.get("name")
        if not company_name_str:
             company_name_str = company.get("id")

        last_exc = None
        for attempt in range(1, self.retry + 1):
            try:
                logger.info(
                    "TallyWorkerAgent: fetching report '%s' for company '%s'",
                    report_name, company_name_str
                )
                
                
                raw = get_report.invoke({
                    "company_name": company_name_str, 
                    "report_name": report_name
                })
                
                if raw is None:
                    return ""
                
                # If tool returned an error dict
                if isinstance(raw, dict) and "error" in raw:
                    raise Exception(raw["error"])

                if not isinstance(raw, str):
                    try:
                        raw = json.dumps(raw, ensure_ascii=False)
                    except:
                        raw = str(raw)
                return raw
            except Exception as e:
                last_exc = e
                logger.exception("Error fetching report on attempt %d: %s", attempt, e)
        raise last_exc


class SummarizerAgent:
    """
    Enhanced worker agent for intelligent report summarization with date awareness.
    """

    def __init__(self, *, model_name: Optional[str] = None):
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        
        # Initialize LLM for intelligent extraction
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            from langchain_google_genai import ChatGoogleGenerativeAI
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=0.15,
                google_api_key=api_key,
                max_retries=0,
            )
        else:
            self.llm = None

    def summarize(self, raw: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Intelligently extract and summarize based on user query context.
        Handles date filtering, aggregation, and formatting automatically.
        """
        if not raw:
            raise ValueError("raw content cannot be empty")

        metadata = metadata or {}
        user_query = metadata.get("user_query", "")
        report_name = metadata.get("report_name", "")

        # If no LLM available, fallback to basic tool
        if not self.llm:
            try:
                summary = summarize_text.invoke({"text": raw})
                return str(summary) if summary else "Summary not available"
            except Exception as e:
                logger.exception("Error during summarization: %s", e)
                return f"Error: {str(e)}"

        # ============ ENHANCED PROMPT WITH DATE/TIME AWARENESS ============
        prompt = f"""
You are a financial data extraction expert for Tally ERP reports.

REPORT TYPE: {report_name}
USER QUERY: {user_query}

RAW REPORT DATA:
{raw[:200000]}

CRITICAL INSTRUCTIONS:

1. **DATE/TIME FILTERING:**
   - If user query mentions dates (FY 2024-25, April 2025, March 2025, etc.)
     → ONLY extract data matching those dates from the report
   - Ignore all other date ranges present in the report
   - FY 2024-25 = April 2024 to March 2025
   - If query says "next 30 days", calculate from today's date

2. **AGGREGATION PATTERNS:**
   - "monthly" → Group by month and show month-wise data
   - "quarterly" → Group by quarter (Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar)
   - "daily" → Show day-wise data
   - "per month" → Same as monthly
   - "month-wise" → Same as monthly
   - "per customer" → Group by customer name
   - "item-wise" → Group by item/product name

3. **OUTPUT FORMAT:**
   - For MONTHLY data: Show as "Month YYYY: ₹amount"
   - For QUARTERLY data: Show as "Q1 FY24-25: ₹amount"
   - For DAILY data: Show as "DD-MMM-YYYY: ₹amount"
   - For CUSTOMER/ITEM-wise: Show as "Name: ₹amount"
   - Always use Indian Rupee symbol (₹)
   - Format large numbers with commas (₹12,45,000)

4. **PRECISION:**
   - Return EXACT numbers from report (no rounding unless asked)
   - Include currency symbol if present (₹)
   - Preserve original formatting where possible

5. **SCOPE:**
   - Extract ONLY what's asked
   - DO NOT add extra analysis or commentary
   - DO NOT explain methodology
   - DO NOT include data outside requested date range
6. **SLIGHT EXPANSION RULE:**
   - If the answer is very short (1 line or 1 value), expand it slightly by:
     • adding the exact date range used
     • adding a clear label (Sales / Profit / Outstanding / Stock etc.)
   - Keep the response concise (max 4–6 lines)
   - Do NOT add analysis or explanation

Do NOT use the words "Thought:" or "Action:" in the response.

EXAMPLES:

Query: "Show monthly sales for FY 2024-25"
Report contains: Jan-2024 to Dec-2025 data
Answer: 
"Monthly Sales (FY 2024-25):
- Apr-2024: ₹12,45,000
- May-2024: ₹15,20,000
- Jun-2024: ₹18,30,000
- Jul-2024: ₹14,50,000
- Aug-2024: ₹16,80,000
- Sep-2024: ₹19,20,000
- Oct-2024: ₹17,50,000
- Nov-2024: ₹20,10,000
- Dec-2024: ₹22,30,000
- Jan-2025: ₹21,50,000
- Feb-2025: ₹19,80,000
- Mar-2025: ₹23,40,000"

Query: "Show sales for April 2025"
Report contains: Full year data
Answer:
"Sales (April 2025):
- Total Sales: ₹3,25,000
- Number of Invoices: 45
- Average Order Value: ₹7,222"

Query: "Show quarterly gross profit for FY 2024-25"
Answer:
"Quarterly Gross Profit (FY 2024-25):
- Q1 (Apr-Jun 2024): ₹45,95,000
- Q2 (Jul-Sep 2024): ₹50,20,000
- Q3 (Oct-Dec 2024): ₹59,90,000
- Q4 (Jan-Mar 2025): ₹64,35,000"

Query: "Show customer-wise outstanding amount"
Answer:
"Customer-wise Outstanding:
1. ABC Traders: ₹5,20,000
2. XYZ Enterprises: ₹3,15,000
3. DEF Industries: ₹2,80,000
4. GHI Corp: ₹1,95,000"

Query: "Bills due in next 30 days"
Today: 18-Jan-2025
Answer:
"Bills Due (18-Jan-2025 to 17-Feb-2025):
1. Customer A: ₹50,000 (Due: 25-Jan-2025)
2. Customer B: ₹30,000 (Due: 05-Feb-2025)
3. Customer C: ₹20,000 (Due: 12-Feb-2025)
Total: ₹1,00,000"

Query: "What is my costliest stock item?"
Answer: "Costliest Item: Premium Widget (Rate: ₹15,000 per unit)"

NOW EXTRACT FROM THE REPORT ABOVE BASED ON THE USER QUERY:
"""

        try:
            response = self.llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.exception("LLM summarization error: %s", e)
            # Fallback to basic tool
            try:
                summary = summarize_text.invoke({"text": raw})
                return str(summary) if summary else "Summary not available"
            except:
                return f"Could not extract data. Error: {str(e)}"