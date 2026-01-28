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
You are a financial data extraction and summarization expert for Tally ERP reports.

REPORT TYPE: {report_name}
USER QUERY: {user_query}

RAW REPORT DATA:
{raw[:200000]}

YOUR TASK: Extract and present the data based on the user's request.

===============================================================================
CLASSIFICATION: Determine the query type first
===============================================================================

TYPE 1: GENERIC SUMMARY (no specific dates/filters)
Examples:
- "Summarize balance sheet"
- "Show profit & loss"
- "What's in the stock summary?"
- "Give me balance sheet overview"

For these → Provide a CLEAN OVERVIEW of ALL major items with their values.

TYPE 2: DATE-FILTERED QUERY
Examples:
- "Show monthly sales for FY 2024-25"
- "Sales for April 2025"
- "Quarterly profit"

For these → ONLY extract data matching the specified date range.

TYPE 3: SPECIFIC VALUE QUERY
Examples:
- "What is capital account value?"
- "Show current liabilities"
- "What's my costliest item?"

For these → Extract the EXACT value requested.

===============================================================================
INSTRUCTIONS BY TYPE
===============================================================================

TYPE 1: GENERIC SUMMARY
-----------------------------
- Show ALL major line items from the report
- Format as clean list with values
- Use bullet points (-)
- Include proper labels and amounts
- Group related items if needed

Example Output:
"Balance Sheet Summary:

Liabilities:
- Capital Account: ₹77,65,000
- Loans (Liability): ₹40,30,000
- Current Liabilities: ₹92,77,000

Assets:
- Fixed Assets: ₹10,62,000 (negative indicates reduction)
- Current Assets: ₹80,74,000 (negative)
- Investments: ₹3,11,000 (negative)

Net Position: The company shows capital of ₹77.65 lakhs with total liabilities of ₹1.33 crores."

TYPE 2: DATE-FILTERED
--------------------------
Apply STRICT date filtering:
- FY 2024-25 = April 2024 to March 2025
- "monthly" → Group by month
- "quarterly" → Group by quarter (Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar)
- "daily" → Show day-wise

Example Output:
"Monthly Sales (FY 2024-25):
- Apr-2024: ₹12,45,000
- May-2024: ₹15,20,000
- Jun-2024: ₹18,30,000
..."

TYPE 3: SPECIFIC VALUE
---------------------------
Extract ONLY the requested value(s).

Example Output:
"Capital Account: ₹77,65,688"

===============================================================================
FORMATTING RULES (APPLY TO ALL TYPES)
===============================================================================

1. **CURRENCY:**
   - Always use ₹ symbol
   - Format with commas: ₹12,45,000
   - For lakhs/crores: ₹77.65 lakhs or ₹1.33 crores

2. **NEGATIVE VALUES:**
   - Show negative with minus: -₹10,62,000
   - Explain if needed: "(negative indicates reduction/outflow)"

3. **STRUCTURE:**
   - Use bullet points (-) for lists
   - Group related items under headers
   - Keep it concise but complete

4. **PRECISION:**
   - Use exact numbers from report
   - Round only for readability (show 2 decimals max)
   - Preserve original formatting where possible

===============================================================================
CRITICAL RULES
===============================================================================

DO:
- Extract ALL major items for generic queries
- Apply date filters ONLY when dates mentioned
- Use clean, readable formatting
- Include context labels (Liabilities, Assets, etc.)
- Handle negative values properly

DON'T:
- Skip items in generic summaries
- Add analysis unless asked
- Use technical jargon
- Invent data not in report
- Use words "Thought:" or "Action:"

===============================================================================
EXAMPLES
===============================================================================

Query: "Summarize balance sheet"
Answer:
"Balance Sheet Summary:

Liabilities:
- Capital Account: ₹77,65,688
- Loans (Liability): ₹40,30,655
- Current Liabilities: ₹92,77,354

Assets:
- Fixed Assets: -₹10,62,367 (negative)
- Investments: -₹31,13,164
- Current Assets: -₹80,74,699

The balance sheet shows positive capital and liabilities totaling ₹2.10 crores, with asset adjustments."

Query: "What is capital account value?"
Answer: "Capital Account: ₹77,65,688"

Query: "Show monthly sales for FY 2024-25"
Answer:
"Monthly Sales (FY 2024-25):
- Apr-2024: ₹25,27,354
- May-2024: ₹70,13,547
- Jun-2024: ₹41,60,664
- Jul-2024: ₹31,83,443
- Aug-2024: ₹56,02,576
- Sep-2024: ₹47,01,513
- Oct-2024: ₹1,68,690
- Nov-2024: ₹0
- Dec-2024: ₹50,30,483
- Jan-2025: ₹25,00,000

Total Sales: ₹3,48,88,270"

Query: "Show profit & loss"
Answer:
"Profit & Loss Summary:

Income:
- Sales Revenue: ₹3,24,86,449
- Other Income: ₹15,23,000

Expenses:
- Operating Expenses: ₹2,10,45,000
- Administrative Costs: ₹45,20,000

Net Profit: ₹84,44,449"

===============================================================================
NOW EXTRACT/SUMMARIZE BASED ON THE USER QUERY ABOVE:
===============================================================================
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