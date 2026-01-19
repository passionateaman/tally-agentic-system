# tools/vega_spec_generator.py
import os
import json
from typing import Dict, Any, List, Optional

# LangChain / Gemini imports
try:
    from langchain.prompts import PromptTemplate
    from langchain.chains import LLMChain
except Exception:
    PromptTemplate = None
    LLMChain = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None

# Deterministic fallback (keeps simple builder if LLM fails)
def _auto_spec(rows: List[Dict[str, Any]], instruction: str) -> Dict[str, Any]:
    safe = []
    for r in rows:
        lbl = r.get("label") if isinstance(r.get("label"), str) else str(r.get("label") or "")
        try:
            v = float(r.get("value")) if r.get("value") is not None else None
        except Exception:
            v = None
        safe.append({"section": r.get("section", "root"), "label": lbl, "value": v, "value_abs": abs(v) if v is not None else None})
    numeric = [r for r in safe if r["value"] is not None]
    if not numeric:
        numeric = safe
    # default bar
    for r in numeric:
        r["_abs"] = r.get("value_abs") or 0.0
    numeric_sorted = sorted(numeric, key=lambda x: x["_abs"], reverse=True)
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"A bar chart of {instruction}",
        "data": {"values": numeric_sorted},
        "mark": "bar",
        "encoding": {
            "x": {"field": "label", "type": "nominal", "sort": "-y"},
            "y": {"field": "value", "type": "quantitative"},
            "tooltip": [{"field": "label", "type": "nominal"}, {"field": "value", "type": "quantitative"}]
        }
    }

GEN_PROMPT = """
Return exactly one valid Vega-Lite v5 JSON object (no surrounding text).
Rules:
- Use the provided DATA_VALUES array (do NOT sample or truncate).
- Use 'label' for categorical field and 'value' (or absolute) for quantitative.
- If user asked for pie, use absolute values for theta.
- Include tooltips for label and value.
User instruction:
{instruction}

DATA_VALUES:
{data_values}
"""

PROMPT_TEMPLATE = PromptTemplate(input_variables=["instruction", "data_values"], template=GEN_PROMPT) if PromptTemplate is not None else None

def _init_gemini_llm(model: Optional[str] = None, temperature: float = 0.0):
    if ChatGoogleGenerativeAI is None:
        return None
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    try:
        if api_key:
            try:
                return ChatGoogleGenerativeAI(model=model or os.getenv("GEMINI_MODEL") or "gemini-1.5-pro", temperature=temperature, google_api_key=api_key)
            except TypeError:
                return ChatGoogleGenerativeAI(model=model or os.getenv("GEMINI_MODEL") or "gemini-1.5-pro", temperature=temperature, api_key=api_key)
        else:
            return ChatGoogleGenerativeAI(model=model or os.getenv("GEMINI_MODEL") or "gemini-1.5-pro", temperature=temperature)
    except Exception:
        return None

def _extract_json(text: str):
    if not isinstance(text, str):
        return None
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        return json.loads(text[s:e+1])
    except Exception:
        # best-effort: try to balance braces
        stack = []
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if start is None:
                    start = i
                stack.append(i)
            elif ch == "}":
                if stack:
                    stack.pop()
                    if not stack and start is not None:
                        try:
                            return json.loads(text[start:i+1])
                        except Exception:
                            start = None
                            continue
        return None

def generate_vega_spec_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload:
      - instruction: str
      - data: {"rows": [...]}
      - llm: optional existing llm instance (preferred)
      - model: optional model name
    Always attempts to call Gemini LLM to generate the spec.
    Falls back to deterministic spec only if LLM unavailable or returns invalid result.
    """
    instruction = payload.get("instruction", "") or ""
    data = payload.get("data", {}) or {}
    rows = data.get("rows", []) if isinstance(data, dict) else []
    model = payload.get("model") or os.getenv("GEMINI_MODEL")

    # prepare data_values string (full rows)
    try:
        data_values_text = json.dumps(rows, ensure_ascii=False, indent=2)
    except Exception:
        data_values_text = str(rows)

    # use provided llm or init one
    llm = payload.get("llm")
    if llm is None:
        llm = _init_gemini_llm(model=model, temperature=0.0)

    # if no LLM available, fallback immediately
    if llm is None or PROMPT_TEMPLATE is None or LLMChain is None:
        return _auto_spec(rows, instruction)

    # build prompt & call LLM
    chain = LLMChain(llm=llm, prompt=PROMPT_TEMPLATE)
    try:
        raw = chain.run({"instruction": instruction, "data_values": data_values_text})
    except Exception:
        return _auto_spec(rows, instruction)

    spec = _extract_json(raw)
    if spec is None:
        # fallback deterministic with LLM raw included for debugging
        fallback = _auto_spec(rows, instruction)
        fallback["_llm_raw_preview"] = raw[:2000]
        return fallback

    # ensure data.values present
    if "data" not in spec or not isinstance(spec["data"], dict):
        spec["data"] = {"values": rows}
    else:
        if "values" not in spec["data"] or not spec["data"]["values"]:
            spec["data"]["values"] = rows

    return spec
