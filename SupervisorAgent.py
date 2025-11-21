import json
import os
from datetime import datetime
from typing import Optional

from langchain.agents import Tool
try:
    from langchain.agents import create_react_agent
    CREATE_REACT_AVAILABLE = True
except Exception:
    CREATE_REACT_AVAILABLE = False
    from langchain.agents import initialize_agent, AgentType

from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.base import BaseCallbackHandler

from langchain_google_genai import ChatGoogleGenerativeAI

try:
    
    from agents import TallyWorkerAgent, SummarizerAgent
except Exception as e:
    raise ImportError(
        "Supervisor requires TallyWorkerAgent and SummarizerAgent in agents.py. "
        "Check that agents.py defines these classes. Original error: " + str(e)
    )

# ---------- Streaming callback handler ----------
class TranscriptStreamingHandler(BaseCallbackHandler):
    def __init__(self, writer=None):
        super().__init__()
        self._buf = ""
        self._writer = writer
        self._write_enabled = callable(writer)

    def _write(self, text: str):
        if self._write_enabled:
            try:
                self._writer(text + "\n")
            except Exception:
                pass

    def on_llm_new_token(self, token: str, **kwargs):
        if not self._buf:
            header = f"\n[Thought stream start @ {datetime.utcnow().isoformat()}]"
            print(header)
            self._write(header)
            print("Thought (stream): ", end="", flush=True)
            self._write("Thought (stream): ")
        print(token, end="", flush=True)
        self._write(token)
        self._buf += token

    def on_llm_end(self, response, **kwargs):
        if self._buf:
            footer = f"\n[Thought stream end @ {datetime.utcnow().isoformat()}]\n"
            print(footer)
            self._write(footer)
            self._buf = ""

    def on_agent_action(self, action, **kwargs):
        log = getattr(action, "log", None) or f"Tool={getattr(action,'tool',None)} Input={getattr(action,'tool_input',None)}"
        out = f"\n=== ACTION @ {datetime.utcnow().isoformat()} ===\n{log}\n=== END ACTION ==="
        print(out)
        self._write(out)

    def on_tool_start(self, tool_input=None, **kwargs):
        marker = f"\n[Tool started @ {datetime.utcnow().isoformat()}]"
        print(marker)
        self._write(marker)

    def on_tool_end(self, output, **kwargs):
        parsed = None
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
            except Exception:
                parsed = None
        else:
            parsed = output

        if parsed is not None:
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            out = f"\n=== OBSERVATION @ {datetime.utcnow().isoformat()} ===\n{pretty}\n=== END OBSERVATION ==="
        else:
            out = f"\n=== OBSERVATION @ {datetime.utcnow().isoformat()} ===\n{output}\n=== END OBSERVATION ==="
        print(out)
        self._write(out)

    def on_agent_finish(self, finish, **kwargs):
        out = f"\n=== AGENT FINISHED @ {datetime.utcnow().isoformat()} ===\n{finish}\n=== END AGENT FINISHED ==="
        print(out)
        self._write(out)


TALLY_AGENT = TallyWorkerAgent()
SUMMARIZER_AGENT = SummarizerAgent()


def tool_fetch_companies(_input: str = "") -> str:
    try:
        companies = TALLY_AGENT.fetch_companies()
        return json.dumps({"status": "ok", "companies": companies}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def tool_list_companies_text(_input: str = "") -> str:
    try:
        companies = TALLY_AGENT.fetch_companies()
        if not companies:
            return "No companies found."
        lines = []
        for i, c in enumerate(companies):
            name = c.get("name", "<unknown>")
            cid = c.get("id", "")
            lines.append(f"{i+1}. {name}" + (f" (id={cid})" if cid else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing companies: {e}"

def tool_fetch_report(input_str: str = "") -> str:
    try:
        payload = {}
        if input_str:
            try:
                payload = json.loads(input_str)
            except Exception:
                payload = {}
        company = payload.get("company")
        report_name = payload.get("report_name")
        if not company or not report_name:
            return json.dumps({"status": "error", "error": "missing company or report_name"})
        # Supervisor calls the worker agent; the worker will call tools internally.
        raw = TALLY_AGENT.fetch_report(company, report_name)
        if not raw:
            return json.dumps({"status": "error", "error": "empty report"})
        return json.dumps({"status": "ok", "report": raw}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def tool_summarize_report(input_str: str = "") -> str:
    try:
        payload = {}
        if input_str:
            try:
                payload = json.loads(input_str)
            except Exception:
                payload = {"raw": input_str}
        raw = payload.get("raw") or ""
        metadata = payload.get("metadata", {})
        if not raw:
            return json.dumps({"status": "error", "error": "no raw content"})
        # Call summarizer agent which will internally call the summarization tool
        summary = SUMMARIZER_AGENT.summarize(raw, metadata=metadata)
        return json.dumps({"status": "ok", "summary": summary}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

# ---------- Compose Tools for LangChain ----------
TOOLS = [
    Tool(name="fetch_companies", func=tool_fetch_companies, description="Call TallyWorkerAgent.fetch_companies()"),
    Tool(name="list_companies_text", func=tool_list_companies_text, description="List companies nicely"),
    Tool(name="fetch_report", func=tool_fetch_report, description="Call TallyWorkerAgent.fetch_report(company, report_name)"),
    Tool(name="summarize_report", func=tool_summarize_report, description="Call SummarizerAgent.summarize(raw, metadata)"),
]

# ---------- Create & run ReAct agent at runtime ----------
def create_and_run_supervisor(model_name: Optional[str] = None, temperature: float = 0.0, transcripts_dir: str = "transcripts"):
    os.makedirs(transcripts_dir, exist_ok=True)
    ts_file = datetime.utcnow().strftime("transcript_%Y%m%dT%H%M%SZ.log")
    ts_path = os.path.join(transcripts_dir, ts_file)
    f = open(ts_path, "a", encoding="utf-8")
    def writer(line: str):
        f.write(line)
        f.flush()

    cb_manager = CallbackManager([TranscriptStreamingHandler(writer)])
    llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)

    if CREATE_REACT_AVAILABLE:
        agent_executor = create_react_agent(llm=llm, tools=TOOLS, callback_manager=cb_manager, verbose=True)
    else:
        agent_executor = initialize_agent(
            tools=TOOLS,
            llm=llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,
            callback_manager=cb_manager
        )

    exemplar = (
        "EXEMPLAR:\n"
        "Thought: fetch companies\n"
        "Action: fetch_companies\n"
        "Observation: {\"status\":\"ok\",\"companies\":[{\"name\":\"Acme\",\"id\":\"c1\"}]}\n\n"
        "Thought: show list and ask user\n"
        "Action: list_companies_text\n"
        "Observation: \"1. Acme (id=c1)\"\n"
        "USER_PROMPT: Please pick a company by number.\n\n"
        "USER_REPLY: 1\n\n"
        "Thought: ask for report name\n"
        "USER_PROMPT: Which report name?\n\n"
        "USER_REPLY: Ledger Vouchers\n\n"
        "Thought: fetch report and summarize\n"
        "Action: fetch_report {\"company\":{\"name\":\"Acme\",\"id\":\"c1\"},\"report_name\":\"Ledger Vouchers\"}\n"
        "Observation: {\"status\":\"ok\",\"report\":\"<xml>...\"}\n"
        "Action: summarize_report {\"raw\":\"<xml>...\",\"metadata\":{\"company\":\"Acme\"}}\n"
        "Observation: {\"status\":\"ok\",\"summary\":\"...\"}\n"
        "FINISHED: Final summary\n"
    )

    task_prompt = (
        "You are a Supervisor ReAct agent. Use tools: fetch_companies, list_companies_text, fetch_report, summarize_report. "
        "When you need user input print exactly: USER_PROMPT: <question>. When finished print exactly: FINISHED: <summary>."
    )

    prompt = exemplar + "\n\n" + task_prompt

    response = agent_executor.run(prompt)
    print("\n=== AGENT RESPONSE ===\n", response)

    while "USER_PROMPT:" in response:
        try:
            prompt_text = response.split("USER_PROMPT:", 1)[1].strip()
        except Exception:
            prompt_text = "Please respond:"
        user_input = input(prompt_text + "\n> ").strip()
        response = agent_executor.run("USER_REPLY: " + user_input)
        print("\n=== AGENT RESPONSE ===\n", response)

    try:
        f.close()
        print(f"\nTranscript saved to: {ts_path}")
    except Exception:
        pass

    return response

# ---------- CLI Entrypoint ----------
if __name__ == "__main__":
    create_and_run_supervisor(model_name=os.getenv("GEMINI_MODEL"), temperature=0.0)
