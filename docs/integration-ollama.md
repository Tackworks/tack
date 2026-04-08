# Using Tack with Ollama / llama.cpp

This guide shows how to wire Tack into a locally-running model via Ollama or llama.cpp's OpenAI-compatible API.

## Setup

```bash
pip install fastapi uvicorn httpx openai
python server.py  # Start Tack on localhost:8795
ollama serve      # Start Ollama (or llama-server)
```

## With Ollama (OpenAI-Compatible)

Ollama exposes an OpenAI-compatible API. Use the same approach as the [OpenAI integration](integration-openai.md), just point at Ollama:

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"  # Ollama doesn't need a real key
)

# Use tools exactly as in the OpenAI guide
response = client.chat.completions.create(
    model="qwen2.5:7b",  # or any model with tool calling support
    messages=messages,
    tools=tools
)
```

## With llama-server

llama.cpp's `llama-server` also supports the OpenAI chat completions format:

```python
client = openai.OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="none"
)

response = client.chat.completions.create(
    model="local",
    messages=messages,
    tools=tools
)
```

## Context-Injection Alternative

For smaller models (7B and under) that struggle with tool calling, inject the board state directly into the prompt instead:

```python
import httpx

# Get board state
board = httpx.get("http://localhost:8795/api/board?fields=id,title,column_name,assignee").json()

# Build context
board_context = "Current board state:\n"
for col, cards in board.items():
    if cards:
        board_context += f"\n{col}:\n"
        for card in cards:
            board_context += f"  - [{card['id']}] {card['title']} (assigned: {card.get('assignee', 'none')})\n"

system = f"""You are a project manager. Here is the task board:

{board_context}

To take actions, output JSON commands like:
{{"action": "create", "title": "...", "assignee": "..."}}
{{"action": "move", "card_id": "card-xxx", "column_name": "done"}}
"""
```

Then parse the model's JSON output and forward to the Tack API.

## Which Models Support Tool Calling?

| Model | Tool Calling | Notes |
|-------|-------------|-------|
| Qwen 2.5 7B+ | Yes | Reliable, recommended |
| Qwen 3 | Yes | Excellent |
| Llama 3.1 8B+ | Yes | Works well |
| Mistral 7B | Partial | Sometimes formats incorrectly |
| Phi-3 | No | Use context injection |

## Tips

- Smaller models work better with context injection than tool calling.
- Use `fields=id,title,column_name` to keep the board state compact.
- Poll with `GET /api/changes?since=...` instead of fetching the full board every time.
- Set `TACK_DONE_ARCHIVE_DAYS=1` during development to keep the board clean.
