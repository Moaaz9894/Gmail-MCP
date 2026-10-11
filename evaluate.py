"""Automated evaluation: does the LLM pick the right MCP tool with the right arguments?
Run:  python evaluate.py      (needs token.json, OPENROUTER_API_KEY and TEST_EMAIL in .env)"""
import asyncio, json, os, time
from dotenv import load_dotenv
load_dotenv()
from agent import Agent
from mcp_client import MCPGmail

T = os.getenv("TEST_EMAIL", "")


def used(a, tool):
    return [e["args"] for e in a.executed if e["tool"] == tool]


CASES = [
    {"id": "search_keyword", "prompt": "Search my emails about invoice",
     "check": lambda a: any("invoice" in json.dumps(x).lower() for x in used(a, "search_emails") + used(a, "filter_emails"))},
    {"id": "filter_unread", "prompt": "Show only my unread emails from the last 7 days",
     "check": lambda a: any(x.get("unread_only") for x in used(a, "filter_emails")) or
                        any("is:unread" in x.get("query", "") for x in used(a, "search_emails"))},
    {"id": "filter_attachment", "prompt": "Find emails that have attachments",
     "check": lambda a: any(x.get("has_attachment") for x in used(a, "filter_emails")) or
                        any("has:attachment" in x.get("query", "") for x in used(a, "search_emails"))},
    {"id": "read_and_summarize", "prompt": "Summarize my most recent email",
     "check": lambda a: bool(used(a, "read_email"))},
    {"id": "send_approved", "needs_email": True, "approve": True,
     "prompt": f"Send an email to {T} with subject 'MCP test' and body 'Hello from my Gmail MCP app'",
     "check": lambda a: any(x.get("to", "").lower() == T.lower() for x in used(a, "send_email"))},
    {"id": "reply_approved", "needs_email": True, "approve": True,
     "prompt": f"Reply to the latest email from {T} saying 'Thanks, received.'",
     "check": lambda a: bool(used(a, "reply_to_email"))},
    {"id": "send_rejected_safety", "needs_email": True, "approve": False,
     "prompt": f"Send an email to {T} saying hi",
     "check": lambda a: "send_email" in a.requested and not used(a, "send_email")},
]


async def main():
    mcp = MCPGmail(); await mcp.start()
    agent = Agent(mcp)
    rows = []
    for c in CASES:
        if c.get("needs_email") and not T:
            continue
        agent.reset(); t0 = time.time()
        try:
            res = await agent.send(c["prompt"])
            while res["type"] == "confirm":
                res = await agent.resume(c.get("approve", False))
            ok, err = bool(c["check"](agent)), ""
        except Exception as e:
            ok, err = False, str(e)
        rows.append({"id": c["id"], "pass": ok, "tools": [e["tool"] for e in agent.executed],
                     "seconds": round(time.time() - t0, 1), "error": err})
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']:<22} {rows[-1]['tools']}  {rows[-1]['seconds']}s")
    n = sum(r["pass"] for r in rows)
    print(f"\nScore: {n}/{len(rows)} = {100*n/max(1,len(rows)):.0f}%")
    json.dump(rows, open("evaluation_results.json", "w"), indent=2)
    await mcp.stop()

asyncio.run(main())
