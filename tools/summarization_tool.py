"""
Summarization Tool - AI-powered report summaries
"""
import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.tools import tool

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp"),
    temperature=0,
    google_api_key=os.getenv("GEMINI_API_KEY")
)

@tool
def summarize_text(report_data: str) -> str:
    """
    Generate an AI summary of a Tally report.
    
    Args:
        report_data: JSON string containing report data
    
    Returns:
        Professional summary of the report
    """
    prompt = f"""You are a financial analyst. Analyze this Tally ERP report and provide a clear summary.

Report Data:
{report_data}

Provide:
1. Report Overview (company, type)
2. Key Financial Figures (extract amounts)
3. Notable Insights
4. Executive Summary (3-5 bullet points)

Format professionally with clear sections."""
    
    try:
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        return f"Error generating summary: {str(e)}"