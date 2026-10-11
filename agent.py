"""LLM agent loop. The LLM picks MCP tools; risky tools need explicit user approval."""
import datetime
import json
import os

from openai import AsyncOpenAI

# Human-in-the-loop: these tools change the outside world, so the app pauses for approval.
CONFIRM_TOOLS = {"send_email", "reply_to_email", "create_auto_filter"}
MAX_STEPS = 8

SYSTEM = """You are a Gmail assistant. You act on the user's mailbox ONLY through the provided tools.
Today's date is {today}.
Rules:
- Use search_emails (Gmail syntax) or filter_emails to find mail; never invent message ids.
- To summarize or reply, first locate the email, then call read_email to see its content.
- To send or reply, call send_email / reply_to_email; the app asks the user to approve it.
- The user usually gives you the MEANING of a message, not its final text. Compose a complete, polite email yourself:
  greeting, clear body expressing that meaning, closing line{signer_rule}. Never paste the user's instruction as the body.
  Always write the email (subject and body) in English, even if the user's instruction is in Arabic or another language, unless they explicitly ask for a different language. Use a formal, professional tone by default.
  Only use exact wording when the user says "exactly", "verbatim", or puts the text in quotes.
  If a needed detail is missing (e.g. the recipient), ask instead of guessing.
- If the user rejects an action, acknowledge it and do not retry.
- Be concise. Present search results as a short list: sender, subject, date."""


class Agent:
    def __init__(self, mcp):
        self.mcp = mcp
        self.llm = AsyncOpenAI(base_url="https://openrouter.ai/api/v1",
                               api_key=os.environ["OPENROUTER_API_KEY"])
        self.model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
        self.reset()

    @staticmethod
    def _signer_rule():
        name = os.getenv("USER_NAME", "").strip()
        return f' and sign it with the name "{name}"' if name else " (do not invent a sender name or signature)"

    def reset(self):
        self.messages = [{"role": "system",
                          "content": SYSTEM.format(today=datetime.date.today().isoformat(),
                                                     signer_rule=self._signer_rule())}]
        self.queue, self.approved = [], None
        self.requested, self.executed, self.turn_trace = [], [], []

    async def send(self, text: str) -> dict:
        self.turn_trace = []
        self.messages.append({"role": "user", "content": text})
        return await self._run()

    async def resume(self, approve: bool) -> dict:
        self.turn_trace = []
        if not self.queue:
            return {"type": "message", "text": "Nothing is waiting for approval.", "trace": []}
        self.approved = approve
        return await self._run()

    def _out(self, **kw):
        return {**kw, "trace": self.turn_trace}

    async def _run(self) -> dict:
        for _ in range(MAX_STEPS):
            if not self.queue:
                try:
                    resp = await self.llm.chat.completions.create(
                        model=self.model, messages=self.messages,
                        tools=self.mcp.openai_tools)
                except Exception as e:
                    return self._out(type="error", text=f"LLM error: {e}")
                msg = resp.choices[0].message
                calls = [{"id": tc.id, "type": "function",
                          "function": {"name": tc.function.name,
                                       "arguments": tc.function.arguments or "{}"}}
                         for tc in (msg.tool_calls or [])]
                entry = {"role": "assistant", "content": msg.content or ""}
                if calls:
                    entry["tool_calls"] = calls
                self.messages.append(entry)
                if not calls:
                    return self._out(type="message", text=msg.content or "")
                self.queue = list(calls)  # copy: popping must not empty the history entry
                self.requested += [c["function"]["name"] for c in calls]

            while self.queue:
                call = self.queue[0]
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError:
                    args = None
                needs_ok = name in CONFIRM_TOOLS
                if needs_ok and self.approved is None:
                    return self._out(type="confirm", tool=name, args=args)
                if args is None:
                    result = "ERROR: invalid JSON arguments"
                elif needs_ok and self.approved is False:
                    result = "The user REJECTED this action. It was not executed."
                else:
                    result = await self.mcp.call_tool(name, args)
                    self.executed.append({"tool": name, "args": args, "result": result})
                    self.turn_trace.append({"tool": name, "args": args})
                self.approved = None
                self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                      "content": result})
                self.queue.pop(0)
        return self._out(type="message", text="Stopped: too many steps.")
