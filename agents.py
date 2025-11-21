
import json
import logging
from typing import Any, Dict, List, Optional

from tools.company_list_tool import get_company_list
from tools.get_report_tool import get_report
from tools.summarization_tool import summarize_text

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class TallyWorkerAgent:
    """
    Worker agent responsible for interacting with Tally-related tools.
    - fetch_companies() -> list[dict]
    - fetch_report(company: dict, report_name: str) -> str (raw xml/text)
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
                comps = get_company_list()
                if comps is None:
                    return []
                if not isinstance(comps, list):
                    return list(comps)
                return comps
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

        last_exc = None
        for attempt in range(1, self.retry + 1):
            try:
                logger.info(
                    "TallyWorkerAgent: fetching report '%s' for company '%s' (attempt %d/%d)",
                    report_name, company.get("name", company.get("id", "<unknown>")),
                    attempt, self.retry
                )
                raw = get_report(company, report_name)
                if raw is None:
                    return ""
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
    Worker agent to summarize raw report text.
    Delegates to the summarize_text tool.
    """

    def __init__(self, *, model_name: Optional[str] = None):
        self.model_name = model_name

    def summarize(self, raw: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Return a summary string."""
        if not raw:
            raise ValueError("raw content cannot be empty")

        metadata = metadata or {}
        try:
            logger.info("SummarizerAgent: summarizing report (metadata=%s)", metadata)
            summary = summarize_text(raw, metadata=metadata)
            if summary is None:
                raise RuntimeError("summarize_text returned None")

            if not isinstance(summary, str):
                try:
                    summary = str(summary)
                except:
                    summary = json.dumps(summary, ensure_ascii=False)

            return summary
        except Exception as e:
            logger.exception("Error during summarization: %s", e)
            raise
