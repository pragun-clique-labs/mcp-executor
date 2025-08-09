# MCP Executor

A FastAPI server that creates and executes MCP (Model Context Protocol) tool bundles.

## Features

- **Bundle Creation**: Break down descriptions into executable tasks using available MCP tools
- **Route Execution**: Execute predefined routes or create new ones on-the-fly
- **LangChain Integration**: Uses LangChain for task planning and execution
- **Supabase Storage**: Persists bundles and routes in Supabase database

## Endpoints

### POST /mcp-bundler
Creates a bundle by analyzing MCP tools and breaking down a description into executable routes.

**Request:**
```json
{
  "project_id": "uuid",
  "mcp_ids": ["uuid1", "uuid2"],
  "description": "Description of what you want to accomplish"
}
```

**Response:**
```json
{
  "bundle_id": "uuid",
  "routes_created": 3
}
```

### POST /executor
Executes a request using existing routes or creates new routes on-the-fly.

**Request:**
```json
{
  "bundle_id": "uuid",
  "request": "What you want to do"
}
```

**Response:**
```json
{
  "result": "Execution results",
  "route_used": "route_uuid",
  "new_route_created": false
}
```

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export SUPABASE_URL=your_supabase_url
export SUPABASE_ANON_KEY=your_supabase_anon_key
export ANTHROPIC_API_KEY=your_anthropic_api_key
```

3. Run the server:
```bash
python main.py
```

## How it Works

1. **Bundle Creation**: The bundler endpoint analyzes available MCP tools and uses LangChain to break down the description into specific tasks, creating routes for each task.

2. **Execution**: The executor endpoint finds matching routes for requests or creates new routes dynamically, then executes them using the MCP tools through LangChain agents.

3. **Storage**: All bundles and routes are stored in Supabase for reuse and tracking.
