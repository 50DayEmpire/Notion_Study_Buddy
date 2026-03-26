# Notion Study Buddy MCP Client

Have you ever felt like your Notion workspace is a "digital graveyard" of notes rather than a living, breathing study tool? Often, the friction between organizing content and actually learning it is where students lose momentum. Study Buddy was built to bridge that gap. It isn't just an assistant; it’s an intelligent orchestrator that transforms your Notion into a dynamic learning partner. Whether you need to generate instant practice quizzes, structure complex pages on new topics, or cross-examine your existing notes to solve critical doubts, Study Buddy leverages the power of LLMs and the Model Context Protocol (MCP) to act directly on your knowledge—letting you focus on mastering the material while the AI handles the management.

An AI-powered Notion assistant that connects a large language model to Notion's MCP server, executes MCP tools safely, and supports both CLI chat and Telegram bot interaction.

## Features

- OAuth 2.0 Authorization Code + PKCE for secure auth
- Dynamic client registration (when needed)
- MCP tool orchestration with iterative tool calls
- Automatic token refresh and re-auth recovery
- Two interaction channels: terminal chat and Telegram

## 🛠️ Tech Stack

### Core & Runtime

- Language: Python 3.13+
- Runtime Pattern: Full asynchronous execution using `asyncio` for non-blocking I/O and concurrent tool handling.
- Protocol Layer: Model Context Protocol (MCP) Python SDK for standardized tool discovery and execution.

### Artificial Intelligence

- Primary LLM Integration: Google Gemini (via `google-genai`) for sophisticated planning and reasoning.
- Alternative LLM Integration: Vultr Serverless Inference for flexible, provider-agnostic model calls.

### Networking & Security

- HTTP Client: `httpx` for high-performance async networking and OAuth exchanges.
- Authentication: OAuth 2.0 + PKCE + Dynamic Client Registration powered by `authlib`, ensuring secure, automated access to Notion's API.
- Local OAuth Callback: Built-in Python `http.server` to handle redirection flows seamlessly without external dependencies.

### Interface & Config

- Bot Interface: `python-telegram-bot` for a mobile-friendly, persistent interaction layer.
- Configuration Management: `python-dotenv` for secure and modular environment variable management.

## Project structure

- `mcpClient.py`: Main MCP client with Gemini-based planning, tool execution loop, and auth recovery
- `telegramBot.py`: Telegram bot entrypoint (private bot with authorized user check)
- `telegramIOAdapter.py`: Adapter layer between Telegram messages and the MCP client
- `auth_service.py`: OAuth flow orchestration (auth code exchange, refresh token logic)
- `auth_utils.py`: OAuth metadata discovery, PKCE generation, registration, token/client persistence
- `localWebServer.py`: Local callback HTTP server for OAuth redirect capture
- `vultrMcpClient.py`: Alternative MCP client variant targeting Vultr Inference API
- `client_credentials.json`: Stored dynamic client credentials (generated)
- `client_tokens.json`: Stored OAuth tokens (generated)

## Architecture at a glance

1. User sends a request (CLI or Telegram).
2. Model plans the next action in strict JSON:
   - tool_call: Executes a Notion action.
   - final: Delivers the result to the user.
3. Client executes MCP tool calls and appends results to tool history.
4. Loop continues until a final answer is produced (with a max tool-call guard).
5. If token is invalid/expired, client attempts refresh; on hard failure, it triggers full re-auth.

## Requirements

- Python 3.13+
- A Google API key (for Gemini in `mcpClient.py`)
- Notion MCP access
- (Optional) Telegram bot token and user id

## Setup

### 1) Install dependencies

Using uv:

```bash
uv sync
```

Or using pip:

```bash
pip install -e .
```

### 2) Configure environment variables

Create a `.env` file in the repository root:

```env
# Required for Gemini SDK
GOOGLE_API_KEY=your_google_api_key

# Optional override (default is https://mcp.notion.com)
BASE_NOTION_URL=https://mcp.notion.com

# Optional override (default is https://mcp.notion.com/mcp)
NOTION_MCP_SERVER_URL=https://mcp.notion.com/mcp

# Telegram mode (required only for telegramBot.py)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_USER_ID=123456789

# Required only if you plan to use vultrMcpClient.py
VULTR_INFERENCE_API_KEY=your_vultr_api_key
```

## Running the app

### CLI mode (interactive terminal)

```bash
python mcpClient.py
```

On first run, the app opens a browser for OAuth consent and captures the callback at:

- http://127.0.0.1:8080/

### Telegram bot mode

```bash
python telegramBot.py
```

The bot accepts messages only from `TELEGRAM_USER_ID`.

## Authentication flow

The OAuth flow follows this sequence:

1. Discover protected resource metadata and authorization server metadata.
2. Generate PKCE verifier/challenge.
3. Dynamically register a client if no client credentials exist.
4. Open browser for user consent.
5. Capture authorization callback with local HTTP server.
6. Exchange code for access/refresh tokens.
7. Persist tokens locally.
8. On future 401 responses, attempt refresh before full re-auth.

## Troubleshooting

### OAuth callback timeout

- Make sure your browser can reach http://127.0.0.1:8080/
- Confirm local firewall is not blocking port 8080

### Unauthorized / token errors

- The client already attempts token refresh automatically.
- If refresh is invalid, it falls back to full re-auth.

### Telegram access denied

- Verify `TELEGRAM_USER_ID` matches your personal Telegram numeric user ID.
