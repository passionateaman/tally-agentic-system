import streamlit as st
import requests

# -----------------------------
# CONFIG
# -----------------------------
API_URL = "http://127.0.0.1:8000/chat"
TIMEOUT = 120
GRAPH_WIDTH = 700

st.set_page_config(
    page_title="Tally Chat – Insights & Graphs",
    layout="wide"
)

st.title("Tally Chat – Insights & Graphs")
def signed_pie_spec(vega_spec):
    values = vega_spec.get("data", {}).get("values", [])
    if not values:
        return vega_spec

    transformed = []
    for v in values:
        val = v.get("value")
        if isinstance(val, (int, float)) and val != 0:
            transformed.append({
                "label": v.get("label"),
                "abs_value": abs(val),   # slice size
                "signed_value": val      # exact hover value
            })

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": transformed},
        "mark": {"type": "arc", "innerRadius": 50},
        "encoding": {
            "theta": {
                "field": "abs_value",
                "type": "quantitative",
                "title": "Magnitude"
            },
            "color": {
                "field": "label",
                "type": "nominal",
                "legend": {"title": "Stock Item"}
            },
            "tooltip": [
                {"field": "label", "type": "nominal", "title": "Item"},
                {
                    "field": "signed_value",
                    "type": "quantitative",
                    "title": "Exact Value"
                }
            ]
        },
        "view": {"stroke": None}
    }


# -----------------------------
# SESSION STATE
# -----------------------------
if "messages" not in st.session_state:
    # role, summary, vega_spec, output_type, raw
    st.session_state.messages = []

# -----------------------------
# RENDER CHAT HISTORY
# -----------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):

        # MARKDOWN TABLE 
        if msg.get("output_type") == "markdown":
            st.markdown(msg.get("summary", ""), unsafe_allow_html=False)

        # GRAPH
        elif msg.get("vega_spec"):
            if msg.get("summary"):
                st.markdown(msg["summary"])

            spec = msg["vega_spec"]

            # detect chart type safely
            mark = spec.get("mark")
            mark_type = mark.get("type") if isinstance(mark, dict) else mark

            # apply signed pie ONLY for pie charts
            if mark_type == "arc":
                spec = signed_pie_spec(spec)

            st.vega_lite_chart(
                spec,
                width=GRAPH_WIDTH
            )


        # TEXT
        else:
            if msg.get("summary"):
                st.markdown(msg["summary"])

        # Optional debug
        if msg.get("raw"):
            with st.expander(" Raw API Response"):
                st.json(msg["raw"])

# -----------------------------
# USER INPUT
# -----------------------------
user_input = st.chat_input("Ask about reports, summaries, or graphs…")

if user_input:
    # Save user message
    st.session_state.messages.append({
        "role": "user",
        "summary": user_input,
        "output_type": "text"
    })

    with st.chat_message("user"):
        st.markdown(user_input)

    # -----------------------------
    # CALL BACKEND
    # -----------------------------
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = requests.post(
                    API_URL,
                    json={"query": user_input},
                    timeout=TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                data = {
                    "output_type": "text",
                    "summary": f" Error contacting API: {e}"
                }

        # -----------------------------
        # NORMALIZE RESPONSE
        # -----------------------------
        output_type = data.get("output_type", "text")
        summary = data.get("summary", "")
        vega_spec = data.get("vega_spec")

        # -----------------------------
        # RENDER RESPONSE
        # -----------------------------
        if output_type == "markdown":
            st.markdown(summary)

        elif vega_spec:
    # Summary already clean from backend
            if summary:
                st.markdown(summary)

            # Render graph
            mark = vega_spec.get("mark")
            mark_type = mark.get("type") if isinstance(mark, dict) else mark

            if mark_type == "arc":
                vega_spec = signed_pie_spec(vega_spec)

            st.vega_lite_chart(vega_spec, width=GRAPH_WIDTH)

        else:
            if summary:
                st.markdown(summary)

    # -----------------------------
    # SAVE ASSISTANT MESSAGE
    # -----------------------------
    st.session_state.messages.append({
        "role": "assistant",
        "summary": summary,
        "vega_spec": vega_spec,
        "output_type": output_type,
        "raw": data
    })
