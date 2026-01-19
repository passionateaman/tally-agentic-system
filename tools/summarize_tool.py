# tools/summarize_tool.py
from langchain.tools import tool
from dotenv import load_dotenv
import google.generativeai as genai
import os

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL")


@tool("summarize_text")
def summarize_text(text: str) -> str:
    """
    Summarize text using Gemini.
    Keys come from .env.
    """

    if not API_KEY:
        return "Missing GEMINI_API_KEY in .env"

    genai.configure(api_key=API_KEY)

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        prompt = f"Summarize this Tally report:\n\n{text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Summary failed: {str(e)}"