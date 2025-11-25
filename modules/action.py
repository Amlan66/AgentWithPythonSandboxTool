# modules/action.py

from typing import Dict, Any, Union
from pydantic import BaseModel
import asyncio
import types
import json
from modules.heuristics import get_validator, HeuristicViolation


# Optional logging fallback
try:
    from agent import log
except ImportError:
    import datetime
    def log(stage: str, msg: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")

class ToolCallResult(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    result: Union[str, list, dict]
    raw_response: Any

MAX_TOOL_CALLS_PER_PLAN = 5

async def run_python_sandbox(code: str, dispatcher: Any) -> str:
    print("[action] 🔍 Entered run_python_sandbox()")
    
    # === HEURISTIC VALIDATION: Plan Safety Check ===
    validator = get_validator()
    is_safe, error_msg = validator.validate_generated_plan(code)
    if not is_safe:
        log("heuristic", f"🚫 Plan validation failed: {error_msg}")
        return f"[sandbox error: Security validation failed - {error_msg}]"

    # Create a fresh module scope
    sandbox = types.ModuleType("sandbox")

    try:
        # Patch MCP client with real dispatcher
        class SandboxMCP:
            def __init__(self, dispatcher):
                self.dispatcher = dispatcher
                self.call_count = 0

            async def call_tool(self, tool_name: str, input_dict: dict):
                self.call_count += 1
                if self.call_count > MAX_TOOL_CALLS_PER_PLAN:
                    raise RuntimeError(f"Exceeded max tool calls ({MAX_TOOL_CALLS_PER_PLAN}) in solve() plan.")
                
                # === HEURISTIC VALIDATION: Tool Call Validation ===
                validator = get_validator()
                available_tools = await self.dispatcher.list_all_tools()
                
                is_valid, errors = await validator.validate_tool_call(
                    tool_name=tool_name,
                    tool_args=input_dict,
                    available_tools=available_tools
                )
                
                if not is_valid:
                    error_summary = "; ".join(errors)
                    log("heuristic", f"🚫 Tool call validation failed: {error_summary}")
                    raise RuntimeError(f"Tool call validation failed: {error_summary}")
                
                # REAL tool call now (with timeout)
                try:
                    timeout = validator.get_timeout_config()
                    result = await validator.execute_with_timeout(
                        self.dispatcher.call_tool(tool_name, input_dict),
                        timeout=timeout
                    )
                    return result
                except asyncio.TimeoutError:
                    raise RuntimeError(f"Tool call to '{tool_name}' timed out after {timeout}s")
                except HeuristicViolation as e:
                    raise RuntimeError(str(e))

        sandbox.mcp = SandboxMCP(dispatcher)

        # Preload safe built-ins into the sandbox
        import json, re
        sandbox.__dict__["json"] = json
        sandbox.__dict__["re"] = re

        # Execute solve fn dynamically
        exec(compile(code, "<solve_plan>", "exec"), sandbox.__dict__)

        solve_fn = sandbox.__dict__.get("solve")
        if solve_fn is None:
            raise ValueError("No solve() function found in plan.")

        if asyncio.iscoroutinefunction(solve_fn):
            result = await solve_fn()
        else:
            result = solve_fn()

        # Clean result formatting
        if isinstance(result, dict) and "result" in result:
            return f"{result['result']}"
        elif isinstance(result, dict):
            return f"{json.dumps(result)}"
        elif isinstance(result, list):
            return f"{' '.join(str(r) for r in result)}"
        else:
            return f"{result}"






    except Exception as e:
        log("sandbox", f"⚠️ Execution error: {e}")
        return f"[sandbox error: {str(e)}]"
