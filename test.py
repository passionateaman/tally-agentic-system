# tools/debug_run_full_pipeline.py
import os
import json
import webbrowser
from pathlib import Path

# Ensure imports use your project code
from tools.tally_report_tool import get_report as direct_get_report
from tools.fetch_report import fetch_report_tool
from tools.json_normalizer import normalize_report_tool
from tools.vega_spec_generator import generate_vega_spec_tool
from tools.vega_renderer import render_vega_html_tool

OUT = Path("debug_outputs")
OUT.mkdir(exist_ok=True)

COMPANY = "Modi Chemplast Materials Pvt Ltd"
REPORT = "Stock Summary"

def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(obj, (dict, list)):
            json.dump(obj, f, ensure_ascii=False, indent=2)
        else:
            f.write(str(obj))

def run_direct_call():
    print("=== 1) Direct lower-level call (tally_report_tool.get_report) ===")
    try:
        raw = direct_get_report(company_name=COMPANY, report_name=REPORT)
    except Exception as e:
        raw = {"error": f"direct_call_failed: {type(e).__name__}: {e}"}
    p = OUT / "direct_raw.json"
    write(p, raw)
    print("Wrote:", p)
    try:
        print("DIRECT RAW (short):")
        s = json.dumps(raw, indent=2, ensure_ascii=False)
        print(s[:4000])
    except Exception:
        print(repr(raw)[:800])
    return raw

def run_fetch_wrapper():
    print("\n=== 2) fetch_report_tool wrapper ===")
    payload = {"company_name": COMPANY, "report_name": REPORT, "try_alternatives": True}
    try:
        res = fetch_report_tool(payload)
    except Exception as e:
        res = {"error": f"fetch_wrapper_failed: {type(e).__name__}: {e}"}
    p = OUT / "fetch_wrapper.json"
    write(p, res)
    print("Wrote:", p)
    try:
        print("FETCH WRAPPER (short):")
        print(json.dumps(res, indent=2, ensure_ascii=False)[:4000])
    except Exception:
        print(repr(res)[:800])
    return res

def extract_parsed(fetch_res):
    if isinstance(fetch_res, dict) and "report" in fetch_res:
        return fetch_res["report"]
    return fetch_res

def run_normalizer(parsed):
    print("\n=== 3) normalize_report_tool ===")
    try:
        norm = normalize_report_tool(parsed)
    except Exception as e:
        norm = {"error": f"normalize_failed: {type(e).__name__}: {e}"}
    p = OUT / "normalized.json"
    write(p, norm)
    print("Wrote:", p)
    try:
        rows = norm.get("rows", [])
        print("ROWS COUNT:", len(rows))
        print(json.dumps(rows, indent=2, ensure_ascii=False)[:5000])
    except Exception:
        print(repr(norm)[:800])
    return norm

def build_forced_spec(norm, force_chart="bar", top_n=None):
    """
    Build deterministic spec from normalized rows (no LLM).
    force_chart: 'bar'|'pie'|'line'|'area'
    top_n: if set and chart is pie, will take top N by absolute and aggregate 'Others'
    """
    rows = norm.get("rows", [])
    # filter nulls
    rows = [r for r in rows if r.get("value") is not None]
    # ensure numeric and compute abs
    def to_num(v):
        try:
            return float(v)
        except Exception:
            return None
    for r in rows:
        r["value"] = to_num(r.get("value"))
        r["_abs"] = abs(r["value"]) if isinstance(r.get("value"), (int, float)) else 0.0

    # sort by absolute desc
    rows_sorted = sorted(rows, key=lambda x: x["_abs"], reverse=True)

    if force_chart == "pie":
        use = rows_sorted
        if top_n and len(use) > top_n:
            top = use[:top_n]
            others_sum = sum(r["_abs"] for r in use[top_n:])
            top.append({"section":"BalanceSheet","label":"Others","value":None,"_abs":others_sum,"theta":others_sum})
            spec_rows = [{"label": r["label"], "theta": (r.get("_abs") or 0.0)} for r in top]
        else:
            spec_rows = [{"label": r["label"], "theta": (r.get("_abs") or 0.0)} for r in use]
        spec = {
            "$schema":"https://vega.github.io/schema/vega-lite/v5.json",
            "data":{"values": spec_rows},
            "mark":{"type":"arc","innerRadius":0},
            "encoding":{
                "theta":{"field":"theta","type":"quantitative"},
                "color":{"field":"label","type":"nominal"},
                "tooltip":[{"field":"label","type":"nominal"},{"field":"theta","type":"quantitative"}]
            }
        }
    else:
        # bar/line/area use label vs value (value may be negative)
        spec_rows = [{"label": r["label"], "value": r["value"]} for r in rows_sorted]
        if force_chart == "line":
            mark = "line"
        elif force_chart == "area":
            mark = "area"
        else:
            mark = "bar"
        spec = {
            "$schema":"https://vega.github.io/schema/vega-lite/v5.json",
            "data":{"values": spec_rows},
            "mark": mark,
            "encoding":{
                "x":{"field":"label","type":"nominal","sort":"-y"},
                "y":{"field":"value","type":"quantitative"},
                "tooltip":[{"field":"label","type":"nominal"},{"field":"value","type":"quantitative"}]
            }
        }
    return spec

def run_spec_generation(norm):
    print("\n=== 4) generate_vega_spec_tool (LLM-based) ===")
    try:
        # call existing tool (may use llm); still produce spec
        spec_via_llm = generate_vega_spec_tool({"instruction": f"Plot a bar chart of {REPORT} showing label vs value", "data": norm, "llm": None})
    except Exception as e:
        spec_via_llm = {"error": f"llm_spec_failed: {type(e).__name__}: {e}"}
    p = OUT / "spec_via_llm.json"
    write(p, spec_via_llm)
    print("Wrote:", p)
    try:
        print("SPEC VIA LLM (short):")
        print(json.dumps(spec_via_llm, indent=2, ensure_ascii=False)[:5000])
    except Exception:
        print(repr(spec_via_llm)[:800])
    return spec_via_llm

def run_forced_spec_and_render(norm, force_chart="bar"):
    print("\n=== 5) Build deterministic spec and render HTML (forced chart:", force_chart, ") ===")
    spec = build_forced_spec(norm, force_chart=force_chart, top_n=10)
    p_spec = OUT / f"spec_forced_{force_chart}.json"
    write(p_spec, spec)
    print("Wrote:", p_spec)
    # ensure values exist
    html_path = render_vega_html_tool({"spec": spec, "out_dir": str(OUT)})
    print("Rendered HTML:", html_path)
    # try to open in default browser (best-effort)
    try:
        webbrowser.open(f"file://{os.path.abspath(html_path)}")
        print("Attempted to open browser.")
    except Exception as e:
        print("Could not open browser:", e)
    return spec, html_path

def main():
    raw = run_direct_call()
    wrapped = run_fetch_wrapper()
    parsed = extract_parsed(wrapped)
    norm = run_normalizer(parsed)
    spec_llm = run_spec_generation(norm)
    spec_forced, html_path = run_forced_spec_and_render(norm, force_chart="bar")
    print("\n=== DONE ===")
    print("Check debug_outputs/ for: direct_raw.json, fetch_wrapper.json, normalized.json, spec_via_llm.json, spec_forced_bar.json and the generated HTML.")

if __name__ == "__main__":
    main()

