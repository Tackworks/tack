# Using Tack with Anthropic Claude Tool Use

This guide shows how to wire Tack into a Claude-powered agent using tool use.

## Setup

```bash
pip install fastapi uvicorn anthropic httpx
python server.py  # Start Tack on localhost:8795
```

## Define Tools

Claude uses a slightly different tool format. Here's how to define Tack tools for Claude:

```python
import anthropic
import json
import httpx

TACK_URL = "http://localhost:8795"
client = anthropic.Anthropic()

tools = [
    {
        "name": "tack_create",
        "description": "Create a new task card on the board",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "description": {"type": "string", "description": "Details and context"},
                "assignee": {"type": "string", "description": "Agent or person responsible"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "critical"]}
            },
            "required": ["title"]
        }
    },
    {
        "name": "tack_list",
        "description": "List cards, optionally filtered. Use fields param to save tokens.",
        "input_schema": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Filter by column name"},
                "assignee": {"type": "string", "description": "Filter by assignee"},
                "fields": {"type": "string", "description": "Comma-separated fields to return"}
            }
        }
    },
    {
        "name": "tack_move",
        "description": "Move a card to a different column",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string"},
                "column_name": {"type": "string", "enum": ["inbox", "approved", "in_progress", "awaiting_decision", "blocked", "done"]},
                "actor": {"type": "string", "description": "Your agent name"}
            },
            "required": ["card_id", "column_name"]
        }
    },
    {
        "name": "tack_note",
        "description": "Add a note to a card's trace log",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string"},
                "content": {"type": "string", "description": "The note content"},
                "author": {"type": "string"}
            },
            "required": ["card_id", "content"]
        }
    }
]
```

## Handle Tool Calls

```python
def execute_tool(name, args):
    if name == "tack_create":
        return httpx.post(f"{TACK_URL}/api/cards", json=args).json()
    elif name == "tack_list":
        params = {k: v for k, v in args.items() if v}
        return httpx.get(f"{TACK_URL}/api/cards", params=params).json()
    elif name == "tack_move":
        card_id = args.pop("card_id")
        return httpx.post(f"{TACK_URL}/api/cards/{card_id}/move", json=args).json()
    elif name == "tack_note":
        card_id = args.pop("card_id")
        return httpx.post(f"{TACK_URL}/api/cards/{card_id}/notes", json=args).json()
    return {"error": f"Unknown tool: {name}"}


def run_agent(user_message):
    messages = [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system="You are a project manager. Use the task board to track work.",
        tools=tools,
        messages=messages
    )

    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system="You are a project manager. Use the task board to track work.",
            tools=tools,
            messages=messages
        )

    return response.content[0].text
```

## Context-Based Alternative

Instead of tool use, you can paste TOOL.md into the system prompt and let Claude make HTTP calls via a generic `http_request` tool. This works well for simpler setups:

```python
tool_spec = open("TOOL.md").read()
system = f"You are a project manager. Here is your task board API:\n\n{tool_spec}"
```

## Tips

- Claude is good at using sparse fields — tell it in the system prompt to use `fields=id,title,column_name` for listing.
- Use `tack_note` to document reasoning. Claude's trace notes make agent-to-agent handoffs much smoother.
- For human-in-the-loop decisions, use the `/decision` endpoint — Claude can formulate structured options well.
