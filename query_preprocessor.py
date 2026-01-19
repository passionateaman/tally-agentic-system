# query_preprocessor.py
"""
Preprocesses user queries to extract:
- Intent (value, summary, comparison, graph, table, company_selection)
- Report type (Balance Sheet, P&L, Stock Summary, Day Book)
- Company mentions
- Key entities (account names, metrics)
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import os
import google.generativeai as genai

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.0-flash-exp")
else:
    gemini_model = None


@dataclass
class QueryContext:
    """Enriched query context for better routing"""
    original_query: str
    normalized_query: str
    intent: str  # value, summary, comparison, graph, table, company_selection
    confidence: float  # 0.0 to 1.0
    report_type: Optional[str]  # Balance Sheet, P&L, Stock Summary, Day Book
    company_mentioned: Optional[str]
    entities: List[str]  # extracted account names, metrics
    output_preference: str  # text, table, graph, auto
    requires_aggregation: bool  # multiple items vs single value
    is_comparative: bool  # comparing multiple things


class QueryPreprocessor:
    """
    Intelligent query preprocessor using rule-based + LLM hybrid approach
    """
    
    # Intent keywords (fallback if LLM unavailable)
    INTENT_PATTERNS = {
        "company_selection": [
            r"\b(use|select|set|switch to|change to)\s+\w+",
            r"^(use|select|set)\s+[\w\s]+$"
        ],
        "table": [
            r"\b(table|tabular|list all|show all|rows)\b",
            r"show.*in.*table",
            r"list.*items"
        ],
        "graph": [
            r"\b(graph|chart|plot|visualize|compare|analysis|trend)\b",
            r"show.*chart",
            r"compare.*based on",
            r"analyse.*by"
        ],
        "value": [
            r"^what is (the )?value",
            r"^how much",
            r"^what's the (total|amount|value)",
            r"\bvalue of\b",
            r"^give me the (value|amount|total)"
        ]
    }
    
    # Report type patterns
    REPORT_PATTERNS = {
        "Stock Summary": [
            r"\b(stock|inventory|items|quantity|rate)\b"
        ],
        "Balance Sheet": [
            r"\b(balance sheet|assets|liabilities|capital|loans|fixed assets|current assets)\b"
        ],
        "Profit & Loss": [
            r"\b(profit|loss|p&l|income|expense|indirect income|indirect expense)\b"
        ],
        "Day Book": [
            r"\b(day book|particulars|voucher|debit amount|credit amount|entries)\b"
        ]
    }
    
    # Company name pattern
    COMPANY_PATTERN = re.compile(r"\b([A-Z][A-Za-z &]+(Pvt\.?\s*Ltd\.?|Limited|Corp|Inc)\.?\s*L?\d*)\b")
    
    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm and gemini_model is not None
        
    def preprocess(self, query: str, conversation_history: Optional[List[str]] = None) -> QueryContext:
        """
        Main preprocessing pipeline
        """
        normalized = self._normalize_query(query)
        
        # Extract company if mentioned
        company = self._extract_company(query)
        
        # Determine output preference
        output_pref = self._detect_output_preference(normalized)
        
        # Extract entities (account names, metrics)
        entities = self._extract_entities(normalized)
        
        # Detect if comparative/aggregation
        is_comparative = self._is_comparative(normalized)
        requires_agg = self._requires_aggregation(normalized)
        
        # Intent classification (LLM or fallback)
        if self.use_llm:
            intent, confidence, report_type = self._classify_with_llm(
                normalized, conversation_history
            )
        else:
            intent, confidence = self._classify_with_rules(normalized)
            report_type = self._infer_report_type(normalized)
        
        return QueryContext(
            original_query=query,
            normalized_query=normalized,
            intent=intent,
            confidence=confidence,
            report_type=report_type,
            company_mentioned=company,
            entities=entities,
            output_preference=output_pref,
            requires_aggregation=requires_agg,
            is_comparative=is_comparative
        )
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query text"""
        # Lowercase
        normalized = query.lower().strip()
        
        # Expand common abbreviations
        replacements = {
            r"\bp&l\b": "profit and loss",
            r"\bbs\b": "balance sheet",
            r"\bpl\b": "profit and loss",
            r"\bqty\b": "quantity",
            r"\bamt\b": "amount"
        }
        
        for pattern, replacement in replacements.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized
    
    def _extract_company(self, query: str) -> Optional[str]:
        """Extract company name from query"""
        match = self.COMPANY_PATTERN.search(query)
        if match:
            company = match.group(1).strip()
            # Clean command words
            company = re.sub(
                r"^(use|select|set|change to|switch to)\s+",
                "",
                company,
                flags=re.IGNORECASE
            )
            return company
        return None
    
    def _detect_output_preference(self, query: str) -> str:
        """Detect if user explicitly wants table/graph/text"""
        q = query.lower()
        
        if any(kw in q for kw in ["table", "tabular", "list all", "show all rows"]):
            return "table"
        
        if any(kw in q for kw in ["graph", "chart", "plot", "visualize"]):
            return "graph"
        
        if any(kw in q for kw in ["explain", "summarize", "describe"]):
            return "text"
        
        return "auto"
    
    def _extract_entities(self, query: str) -> List[str]:
        """Extract account/metric names from query"""
        entities = []
        
        # Common account/metric patterns
        patterns = [
            r"(?:value of|amount of|total)\s+([a-z\s]+?)(?:\s+account|\s+for|\s+in|$)",
            r"([a-z\s]+?)\s+(?:account|liability|asset|expense|income)",
            r"compare\s+([a-z\s]+?)(?:\s+and|\s+vs|\s+with)"
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, query)
            entities.extend([m.strip() for m in matches if m.strip()])
        
        return list(set(entities))
    
    def _is_comparative(self, query: str) -> bool:
        """Check if query involves comparison"""
        comparative_keywords = [
            "compare", "comparison", "vs", "versus", "between",
            "difference", "top", "bottom", "highest", "lowest",
            "rank", "analyze", "analysis"
        ]
        return any(kw in query for kw in comparative_keywords)
    
    def _requires_aggregation(self, query: str) -> bool:
        """Check if query needs multiple items (not single value)"""
        single_value_patterns = [
            r"^what is (the )?value",
            r"^how much is",
            r"what's the value of \w+",
            r"value of \w+ account$"
        ]
        
        # If matches single value pattern, no aggregation
        if any(re.search(p, query) for p in single_value_patterns):
            return False
        
        # Check for plural/multiple indicators
        multi_indicators = ["all", "items", "stocks", "list", "compare", "top", "bottom"]
        return any(ind in query for ind in multi_indicators)
    
    def _classify_with_rules(self, query: str) -> Tuple[str, float]:
        """Fallback rule-based intent classification"""
        
        # Check patterns in priority order
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    confidence = 0.7  # Rule-based confidence
                    return intent, confidence
        
        # Default to summary with low confidence
        return "summary", 0.5
    
    def _infer_report_type(self, query: str) -> Optional[str]:
        """Rule-based report type inference"""
        for report, patterns in self.REPORT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return report
        return None
    
    def _classify_with_llm(
        self,
        query: str,
        conversation_history: Optional[List[str]] = None
    ) -> Tuple[str, float, Optional[str]]:
        """
        Use LLM for intelligent intent classification
        Returns: (intent, confidence, report_type)
        """
        
        context = ""
        if conversation_history:
            context = "Recent conversation:\n" + "\n".join(conversation_history[-3:])
        
        prompt = f"""You are a query classifier for a Tally accounting system.

{context}

Current query: "{query}"

Classify the intent into ONE of these categories:
1. company_selection - User wants to select/change company (e.g., "use Dakshin", "select ABC Ltd")
2. value - User wants a single numeric value (e.g., "what is value of capital account?")
3. summary - User wants textual explanation of a report
4. comparison - User wants to compare multiple items/accounts
5. graph - User explicitly wants visualization (chart/graph)
6. table - User wants data in table format

Also identify the Tally report type:
- Balance Sheet (for assets, liabilities, capital)
- Profit & Loss (for incomes, expenses)
- Stock Summary (for inventory, stock items)
- Day Book (for voucher entries, particulars)
- Group Summary (if unclear)

Respond in this exact format:
INTENT: <category>
CONFIDENCE: <0.0-1.0>
REPORT: <report name or None>
REASON: <brief explanation>"""

        try:
            response = gemini_model.generate_content(prompt)
            text = response.text.strip()
            
            # Parse response
            intent_match = re.search(r"INTENT:\s*(\w+)", text, re.IGNORECASE)
            conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", text)
            report_match = re.search(r"REPORT:\s*([^\n]+)", text, re.IGNORECASE)
            
            intent = intent_match.group(1).lower() if intent_match else "summary"
            confidence = float(conf_match.group(1)) if conf_match else 0.6
            report = report_match.group(1).strip() if report_match else None
            
            if report and report.lower() == "none":
                report = None
            
            return intent, confidence, report
            
        except Exception as e:
            print(f"LLM classification failed: {e}, falling back to rules")
            intent, conf = self._classify_with_rules(query)
            report = self._infer_report_type(query)
            return intent, conf, report


# Singleton instance
_preprocessor = QueryPreprocessor(use_llm=True)

def preprocess_query(query: str, conversation_history: Optional[List[str]] = None) -> QueryContext:
    """Convenience function for preprocessing"""
    return _preprocessor.preprocess(query, conversation_history)