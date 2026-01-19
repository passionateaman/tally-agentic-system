import gradio as gr
import requests
import json
import base64

# -----------------------------
# CONFIG
# -----------------------------
API_URL = "http://127.0.0.1:8000/chat"
TIMEOUT = 120

EMPTY_HTML = "<div></div>"

# -----------------------------
# SAFE VEGA RENDERER
# -----------------------------
def render_vega(spec: dict) -> str:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
      <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
      <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
      <style>
        body {{
            margin: 0;
            padding: 0;
        }}
      </style>
    </head>
    <body>
      <div id="vis"></div>
      <script>
        const spec = {json.dumps(spec)};
        vegaEmbed('#vis', spec, {{ actions: false }});
      </script>
    </body>
    </html>
    """

    encoded = base64.b64encode(html.encode("utf-8")).decode("utf-8")

    return f"""
    <iframe
        src="data:text/html;base64,{encoded}"
        width="100%"
        height="500"
        frameborder="0">
    </iframe>
    """

# -----------------------------
# CHAT HANDLER (MINIMAL FIX)
# -----------------------------
def chat(user_msg, history):
    history = history or []

    # User message
    history.append(f"**User:** {user_msg}")

    try:
        r = requests.post(
            API_URL,
            json={"query": user_msg},
            timeout=TIMEOUT
        )
        r.raise_for_status()
        data = r.json()

    except Exception as e:
        history.append(f"**Assistant:** ❌ Backend Error: {e}")
        return "\n\n---\n\n".join(history), EMPTY_HTML, history

    output_type = data.get("output_type", "text")
    summary = data.get("summary", "No response")

    # Assistant text
    history.append(f"**Assistant:** {summary}")

    # Graph handling (SAFE)
    if output_type == "graph":
        spec = data.get("vega_spec")
        if isinstance(spec, dict):
            return (
                "\n\n---\n\n".join(history),
                render_vega(spec),
                history
            )

    return "\n\n---\n\n".join(history), EMPTY_HTML, history


# -----------------------------
# GRADIO UI (ORIGINAL STYLE)
# -----------------------------
with gr.Blocks(title="Tally Chat – Insights & Graphs") as app:
    gr.Markdown("## 💬 Tally Chat – Insights & Graphs")

    chat_md = gr.Markdown()
    chart = gr.HTML(value=EMPTY_HTML)

    state = gr.State([])

    with gr.Row():
        txt = gr.Textbox(
            placeholder="Ask: plot balance sheet in bar chart",
            scale=4
        )
        btn = gr.Button("Send", scale=1)

    btn.click(
        chat,
        inputs=[txt, state],
        outputs=[chat_md, chart, state],
    )

    txt.submit(
        chat,
        inputs=[txt, state],
        outputs=[chat_md, chart, state],
    )

# -----------------------------
# LAUNCH (IMPORTANT)
# -----------------------------
app.launch(
    share=True,
    show_api=False   #  schema error se bachata hai
)
