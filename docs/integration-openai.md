# Using Tack with OpenAI Function Calling

This guide shows how to wire Tack into an OpenAI-powered agent using function calling.

## Setup

```bash
pip install fastapi uvicorn openai
python server.py  # Start Tack on localhost:8795
```

## Define Tools

Copy the tool definitions from [TOOL.md](../TOOL.md) into your OpenAI `tools` parameter:

```python
import openai
import json
import httpx

TACK_URL = "http://localhost:8795"
client = openai.OpenAI()

# Tool definitions from TOOL.md
tools = [
    {
        "type": "function",
        "function": {
            "name": "tack_create",
            "description": "Create a new task card on the board",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "assignee": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "critical"]}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tack_list",
            "description": "List cards, optionally filtered by column or assignee",
            "parameters": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "assignee": {"type": "string"},
                    "fields": {"type": "string"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tack_move",
            "description": "Move a card to a different column",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string"},
                    "column_name": {"type": "string"},
                    "actor": {"type": "string"}
                },
                "required": ["card_id", "column_name"]
            }
        }
    }
]
```

## Handle Tool Calls

```python
def execute_tool(name, args):
    """Route tool calls to Tack API."""
    if name == "tack_create":
        resp = httpx.post(f"{TACK_URL}/api/cards", json=args)
        return resp.json()
    elif name == "tack_list":
        params = {}
        if "column" in args: params["column"] = args["column"]
        if "assignee" in args: params["assignee"] = args["assignee"]
        if "fields" in args: params["fields"] = args["fields"]
        resp = httpx.get(f"{TACK_URL}/api/cards", params=params)
        return resp.json()
    elif name == "tack_move":
        card_id = args.pop("card_id")
        resp = httpx.post(f"{TACK_URL}/api/cards/{card_id}/move", json=args)
        return resp.json()
    return {"error": f"Unknown tool: {name}"}


def run_agent(user_message):
    messages = [
        {"role": "system", "content": "You are a project manager. Use the task board to track work."},
        {"role": "user", "content": user_message}
    ]

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=tools
    )

    while response.choices[0].message.tool_calls:
        msg = response.choices[0].message
        messages.append(msg)

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            result = execute_tool(call.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result)
            })

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools
        )

    return response.choices[0].message.content
```

## Usage

```python
print(run_agent("Create a task to research database options, high priority"))
print(run_agent("What tasks are in the inbox?"))
print(run_agent("Move card-abc12345 to in_progress"))
```

## Tips

- Use `fields=id,title,column_name` when listing cards to save tokens.
- Set `assignee` to your agent's name so you can filter by it later.
- Use `tack_claim` before starting work to prevent other agents from grabbing the same card.
