# tools/vega_renderer.py
import json
import os
from datetime import datetime

HTML_TEMPLATE = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Vega-Lite Plot</title>
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  </head>
  <body>
    <div id="vis"></div>
    <script type="text/javascript">
      const spec = {spec_json};
      // actions option is a JS object; keep braces literal by doubling in f-string above
      vegaEmbed('#vis', spec, {{actions: false}});
    </script>
  </body>
</html>
"""

def render_vega_html_tool(payload: dict) -> str:
    spec = payload.get("spec", {})
    out_dir = payload.get("out_dir", os.getcwd())

    fname = f"vega_plot_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.html"
    path = os.path.join(out_dir, fname)

    spec_json = json.dumps(spec, ensure_ascii=False)
    html = HTML_TEMPLATE.format(spec_json=spec_json)

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path
