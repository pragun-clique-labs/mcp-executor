import json
import os
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_core.output_parsers import PydanticOutputParser
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(url, key)

app = FastAPI(title="MCP Executor", version="1.0.0")

# Pydantic models for API
class BundlerRequest(BaseModel):
    project_id: str
    mcp_ids: List[str]
    description: str

class BundlerResponse(BaseModel):
    bundle_id: str
    routes_created: int

class ExecutorRequest(BaseModel):
    bundle_id: str
    request: str

class ExecutorResponse(BaseModel):
    result: Any
    route_used: str = None
    new_route_created: bool = False

# Pydantic models for structured output
class Task(BaseModel):
    task_description: str
    tool_sequence: List[str]
    notes: str = ""

class TaskPlanning(BaseModel):
    tasks: List[Task]

class RouteExecution(BaseModel):
    matched_route: bool
    route_used: str = ""
    execution_result: str
    new_route_created: bool = False

@app.post("/mcp-bundler", response_model=BundlerResponse)
async def create_bundle(request: BundlerRequest):
    """Create a bundle by breaking down description into tasks and routes"""
    try:
        # Get MCP server configurations
        response = supabase.table('mcp').select('*').in_('id', request.mcp_ids).execute()
        mcp_config = {}
        for mcp in response.data:
            mcp_config[mcp['name']] = mcp['parameters']
        
        # Create bundler agent with structured output
        client = MultiServerMCPClient(mcp_config)
        tools = await client.get_tools()
        
        # Set up structured output parser
        task_parser = PydanticOutputParser(pydantic_object=TaskPlanning)
        
        bundler_prompt = f"""You are a task planning agent. Break down the description into specific tasks and create routes.

Your job:
1. Analyze the description: "{request.description}"
2. Look at available MCP tools and figure out what tasks can be accomplished
3. Create routes (sequences of tool calls) for each task

Available tools: {[tool.name for tool in tools]}

{task_parser.get_format_instructions()}"""
        
        bundler_agent = create_react_agent("anthropic:claude-3-5-sonnet-latest", tools, state_modifier=bundler_prompt)
        
        result = await bundler_agent.ainvoke({
            "messages": [{"role": "user", "content": f"Plan tasks for: {request.description}"}]
        })
        
        # Parse the structured output
        agent_response = result['messages'][-1].content
        try:
            task_planning = task_parser.parse(agent_response)
            tasks = [task.dict() for task in task_planning.tasks]
        except:
            # Fallback - create a simple task
            tasks = [{
                "task_description": request.description,
                "tool_sequence": [tool.name for tool in tools[:3]],  # Use first 3 tools
                "notes": "Auto-generated from description"
            }]
        
        # Create bundle in database
        bundle_response = supabase.table('bundles').insert({
            'project_id': request.project_id,
            'description': request.description,
            'mcps': request.mcp_ids,
            'routes': []
        }).execute()
        
        bundle_id = bundle_response.data[0]['id']
        
        # Create routes
        route_ids = []
        for i, task in enumerate(tasks):
            route_response = supabase.table('route').insert({
                'bundle_id': bundle_id,
                'task_description': task['task_description'],
                'tool_sequence': task['tool_sequence'],
                'notes': task.get('notes', ''),
                'execution_order': i,
                'mcp_tools': request.mcp_ids
            }).execute()
            route_ids.append(route_response.data[0]['id'])
        
        # Update bundle with routes
        supabase.table('bundles').update({'routes': route_ids}).eq('id', bundle_id).execute()
        
        return BundlerResponse(bundle_id=bundle_id, routes_created=len(tasks))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/executor", response_model=ExecutorResponse)
async def execute_request(request: ExecutorRequest):
    """Execute a request using existing routes or create new route on the fly"""
    try:
        # Get bundle info
        bundle_response = supabase.table('bundles').select('*').eq('id', request.bundle_id).execute()
        if not bundle_response.data:
            raise HTTPException(status_code=404, detail="Bundle not found")
        
        bundle = bundle_response.data[0]
        
        # Get routes
        routes_response = supabase.table('route').select('*').eq('bundle_id', request.bundle_id).order('execution_order').execute()
        routes = routes_response.data
        
        # Get MCP configuration
        mcp_response = supabase.table('mcp').select('*').in_('id', bundle['mcps']).execute()
        mcp_config = {}
        for mcp in mcp_response.data:
            mcp_config[mcp['name']] = mcp['parameters']
        
        # Create executor agent with structured output
        client = MultiServerMCPClient(mcp_config)
        tools = await client.get_tools()
        
        # Set up structured output parser
        execution_parser = PydanticOutputParser(pydantic_object=RouteExecution)
        
        # Build context about available routes
        routes_context = "\n".join([
            f"Route {i+1} (ID: {route['id']}): {route['task_description']} (Tools: {route['tool_sequence']})"
            for i, route in enumerate(routes)
        ])
        
        executor_prompt = f"""You are an MCP executor agent. You have access to these pre-defined routes:

{routes_context}

For the user request: "{request.request}"

1. First check if any existing route matches the request
2. If yes, execute that route using the specified tools and set matched_route=true, route_used=route_id
3. If no route matches, create a new route and execute it, set matched_route=false, new_route_created=true

Bundle description: {bundle['description']}
Available tools: {[tool.name for tool in tools]}

Execute the request and provide the structured output.

{execution_parser.get_format_instructions()}"""
        
        executor_agent = create_react_agent("anthropic:claude-3-5-sonnet-latest", tools, state_modifier=executor_prompt)
        
        result = await executor_agent.ainvoke({
            "messages": [{"role": "user", "content": request.request}]
        })
        
        # Parse the structured output
        agent_response = result['messages'][-1].content
        try:
            execution_result = execution_parser.parse(agent_response)
            return ExecutorResponse(
                result=execution_result.execution_result,
                route_used=execution_result.route_used if execution_result.route_used else (routes[0]['id'] if routes else "new_route"),
                new_route_created=execution_result.new_route_created
            )
        except:
            # Fallback response
            return ExecutorResponse(
                result=result['messages'][-1].content,
                route_used=routes[0]['id'] if routes else "new_route_created",
                new_route_created=len(routes) == 0
            )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
