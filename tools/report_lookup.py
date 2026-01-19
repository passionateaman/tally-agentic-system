# tools/report_lookup.py
from langchain.tools import tool
try:
    from vector_store import get_best_report
except ImportError:
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vector_store import get_best_report

@tool("lookup_tally_report")
def lookup_tally_report(query: str) -> str:
    """
    Input a user's question (e.g., 'how much cash do we have?').
    Returns the EXACT Report Name to use with Tally (e.g., 'Cash/Bank Book').
    ALWAYS use this before fetching data.
    """
    return get_best_report(query)