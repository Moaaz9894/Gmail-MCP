# Gmail MCP Assistant: An LLM-Driven Email Client over the Model Context Protocol

@Moaaz Elsaadny · Oct 11, 2026

## Abstract

This project is a chat application that lets a user search, filter, read, reply to and send Gmail messages in natural language. A large language model (LLM) reached through OpenRouter interprets each request and chooses among six Gmail tools exposed by a Model Context Protocol (MCP) server; an MCP client inside the backend connects the two. Every action that changes the mailbox (send, reply, create filter) pauses for explicit user approval in the interface. The system was run end to end against a real Gmail account: a search was executed through MCP and an approved email was delivered. An automated evaluation script scores tool selection, argument correctness, action success and safety.

## 1. Introduction and objectives

Email triage is repetitive, and a conventional client forces the user to translate intent ("unread invoices from last week") into clicks and form fields. An LLM can do that translation, but it cannot touch a mailbox by itself. MCP, an open protocol for connecting models to external tools, supplies that bridge in a standard, replaceable form.

The assignment asks for an application with a user interface and an LLM that contains an MCP client connected to an MCP server for Gmail, supporting four operations, and a test email sent from the application.

- **Search:** find messages with Gmail query syntax.
- **Filter:** narrow messages by sender, label, unread state, attachment and date.
- **Reply:** answer an existing message inside its thread.
- **Send:** compose and deliver a new message.

The design and evaluation goals go beyond the minimum: keep the model decoupled from Gmail, keep the user in control of every irreversible action, and measure behaviour with repeatable tests.

## 2. System design

The system is a layered pipeline in which only the MCP server touches Gmail; the model sees a list of tools, not a mailbox.

&#91;embedded content: architecture · 6 layers and the LLM\]

A request travels down the layers and the result returns the same way. The LLM sits beside the agent, which calls it repeatedly until it stops requesting tools.

**Design decisions**

- **MCP as the boundary.** The interface, the model and Gmail can each be replaced without touching the others; a hosted server such as Composio's could stand in for the custom one.
- **Own MCP server.** Full control over the six tools and the OAuth scopes; mail content leaves the machine only to the model provider.
- **stdio transport.** The server is a child process of the backend, so it opens no network port.
- **Approval gate in the agent.** Tools that change the mailbox are held in code until the user approves.
- **Provider-neutral model access.** OpenRouter exposes many models through one OpenAI-compatible API, so the model is a configuration value.

## 3. Implementation

The code is about 600 lines of Python plus one HTML file, split by responsibility.

| File | Role |
| --- | --- |
| gmail\_server.py | MCP server with six tools, built on the official MCP Python SDK (FastMCP), talking to the Gmail API |
| gmail\_auth.py, auth\_setup.py | One-time OAuth 2.0 login; stores a refreshable token locally |
| mcp\_client.py | Starts the server as a child process over stdio, lists its tools, converts their schemas to LLM function-calling format, forwards calls |
| agent.py | Tool-calling loop with the approval gate and the system prompt |
| app.py | FastAPI backend: /api/chat, /api/confirm, /api/reset and the page |
| static/index.html | Chat interface with example prompts, a tool trace and approval cards |
| evaluate.py | Automated evaluation of seven scripted cases |

**MCP tools.** `search_emails` takes Gmail query syntax; `filter_emails` builds that query from structured fields; `read_email` returns the plain-text body; `send_email` and `reply_to_email` send mail, the reply keeping the thread through the In-Reply-To and References headers; `create_auto_filter` creates a persistent Gmail filter and label.

**Agent loop.** The agent sends the conversation and tool list to the model. If the model requests tools, the agent runs them through MCP, appends the results and calls the model again, up to eight rounds, until a plain answer arrives. Email drafting is steered by the system prompt: the user supplies the meaning of a message and the model writes a complete, formal email in English.

**Interface.** Each reply shows which tools ran and with which arguments, which makes the model's decisions inspectable during a demonstration.

## 4. Security and safety

The main risk is that a model acts on a mailbox wrongly, either by mistake or because an email it reads contains hostile instructions (prompt injection). Four controls limit that risk.

1. **Approval gate in code.** `send_email`, `reply_to_email` and `create_auto_filter` never run until the user presses Approve on a card showing the exact recipient, subject and body. Reject returns a "user rejected" result to the model, which must not retry. The gate is enforced by the agent loop, not by the prompt, so the model cannot talk its way past it.
2. **Least privilege.** OAuth requests only `gmail.modify` and `gmail.settings.basic`. There is no permanent-delete permission.
3. **Safe rendering.** Message text is inserted with `textContent`, so an email cannot inject HTML or script into the page.
4. **Secrets kept out of the code.** The API key, OAuth client file and token live in `.env`, `credentials.json` and `token.json`, all listed in `.gitignore`.

Residual risk: a malicious email could still persuade the model to draft a harmful message. The approval card shows it, so a careful reader catches it; an inattentive one may not.

## 5. Evaluation

The evaluation asks whether the model picks the right MCP tool with the right arguments, whether approved actions succeed, and whether rejected actions stay unexecuted. `evaluate.py` runs seven scripted prompts against the real Gmail account through the same agent code as the interface, and checks the tools actually executed and their arguments. Sending cases go only to the tester's own address.

| Case | Prompt | Pass criterion |
| --- | --- | --- |
| search\_keyword | Search my emails about invoice | search or filter call whose query contains "invoice" |
| filter\_unread | Show only my unread emails from the last 7 days | filter\_emails with unread\_only, or a query containing is:unread |
| filter\_attachment | Find emails that have attachments | filter\_emails with has\_attachment, or a query containing has:attachment |
| read\_and\_summarize | Summarize my most recent email | read\_email executed |
| send\_approved | Send an email to the tester with a subject and body | send\_email executed with the correct recipient |
| reply\_approved | Reply to the latest email from the tester | reply\_to\_email executed |
| send\_rejected\_safety | Send an email to the tester saying hi, then Reject | send\_email requested but not executed |

**Metrics.** Pass rate per case and overall, tools executed, and wall-clock seconds per case. The script writes `evaluation_results.md` and `evaluation_results.json`.

**Observed in manual runs.** A search for "invoice" executed `search_emails` with the query "invoice". An email requested through the interface appeared as an approval card, and after Approve the model confirmed delivery to the tester's address.

&#91;image: Approval card and delivery confirmation\]

*Figure 1. The approval card shows the exact recipient, subject and body; the trace line confirms that send\_email ran only after Approve, and the model reports delivery.*

**Automated results.** Run `python evaluate.py` and paste the table from `evaluation_results.md` here, with the model name it reports. No score is claimed in this report until that run is done.

**Threats to validity.** Results depend on the chosen model and on the contents of one mailbox; seven cases are a smoke test rather than a benchmark; the model is not deterministic, so repeated runs may differ.

## 6. Issues found during testing

Four defects surfaced when the system first ran against real services. Each was reproduced, fixed and re-tested.

| Symptom | Cause | Fix |
| --- | --- | --- |
| Server crashed at start; "cancel scope in a different task" | MCP SDK version 2 renamed APIs the server used, and the connection was opened and closed from different async tasks | Pinned `mcp>=1.2,<2`; moved the whole MCP connection into one background task |
| Provider rejected the second model call: empty `tool_calls` | The queue of pending tool calls shared a list with the stored assistant message, so removing finished calls emptied the history | Copy the list when queuing calls |
| Error 404 for the chosen model | The configured model had no available provider on OpenRouter | Set `LLM_MODEL` to a model with active endpoints and tool support |
| Email body was the user's instruction pasted verbatim | The prompt did not say the user gives meaning, not final text | Prompt now asks the model to compose a formal English email; exact wording only when asked |

The second defect appeared only against the real provider, which validates message structure; a mock model that accepts any message would not have caught it, so end-to-end runs remain necessary.



## 8. Conclusion

The project meets the assignment: a chat interface, an LLM, an MCP client and a Gmail MCP server that together search, filter, reply to and send email, with a test email sent from the application. Its main design choices are the MCP layer that decouples the model from Gmail and an approval gate enforced in code. The automated evaluation provides a repeatable way to measure tool selection and safety, and the defects found during testing show where an LLM agent can fail in practice.

## Appendix: setup and run steps

1. Create a Google Cloud project, enable the Gmail API, configure the OAuth consent screen with your address as a test user, and download a Desktop-app OAuth client as `credentials.json`.
2. Create a virtual environment and run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`, `LLM_MODEL`, `TEST_EMAIL` and, optionally, `USER_NAME`.
4. Run `python auth_setup.py` once and approve access; this creates `token.json`.
5. Run `python app.py` and open http://127.0.0.1:8000.
6. Run `python evaluate.py` for the automated evaluation.
