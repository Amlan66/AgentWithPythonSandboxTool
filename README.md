# Agentic AI Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            USER QUERY                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          AGENT.PY                                   │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │ 1. Load config/profiles.yaml                               │     │
│  │ 2. Initialize MultiMCP (all MCP servers)                   │     │
│  │ 3. Validate user input (heuristics)                        │     │
│  │ 4. Create AgentContext (session_id, memory)                │     │
│  │ 5. Initialize & Run AgentLoop                              │     │
│  └────────────────────────────────────────────────────────────┘     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│                         AGENT LOOP                                │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                      max_steps loop                          │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐    │ │
│  │  │              1. PERCEPTION                           │    │ │
│  │  │  • Extract intent, entities, tool_hint               │    │ │
│  │  │  • Select relevant MCP servers                       │    │ │
│  │  │  • Filter available tools                            │    │ │
│  │  └────────────────┬─────────────────────────────────────┘    │ │
│  │                   │                                          │ │
│  │                   ▼                                          │ │
│  │  ┌──────────────────────────────────────────────────────┐    │ │
│  │  │              2. DECISION                             │    │ │
│  │  │  • Select prompt based on strategy mode              │    │ │
│  │  │    - conservative: 1 tool call                       │    │ │
│  │  │    - exploratory parallel: multiple independent calls│    │ │
│  │  │    - exploratory sequential: fallback chain          │    │ │
│  │  │  • LLM generates async solve() function              │    │ │
│  │  └────────────────┬─────────────────────────────────────┘    │ │
│  │                   │                                          │ │
│  │                   ▼                                          │ │
│  │  ┌──────────────────────────────────────────────────────┐    │ │
│  │  │              3. ACTION                               │    │ │
│  │  │  • Validate plan (heuristics)                        │    │ │
│  │  │  • Create Python sandbox                             │    │ │
│  │  │  • Execute solve() function                          │    │ │
│  │  │  • Make MCP tool calls via dispatcher                │    │ │
│  │  │  • Validate tool calls (heuristics)                  │    │ │
│  │  └────────────────┬─────────────────────────────────────┘    │ │
│  │                   │                                          │ │
│  │                   ▼                                          │ │
│  │  ┌──────────────────────────────────────────────────────┐    │ │
│  │  │              4. MEMORY                               │    │ │
│  │  │  • Log tool calls and results                        │    │ │
│  │  │  • Save to memory/YYYY/MM/DD/session-{id}.json       │    │ │
│  │  │  • Track success/failure                             │    │ │
│  │  └────────────────┬─────────────────────────────────────┘    │ │
│  │                   │                                          │ │
│  │                   ▼                                          │ │
│  │            ┌──────────────┐                                  │ │
│  │            │ Check Result │                                  │ │
│  │            └───┬──────┬───┘                                  │ │
│  │                │      │                                      │ │
│  │    FINAL_ANSWER│      │FURTHER_PROCESSING_REQUIRED           │ │
│  │                │      └──────────┐                           │ │
│  │                │                 │                           │ │
│  │                │                 ▼                           │ │
│  │                │         Update user_input_overrid           │ │
│  │                │         Continue loop                       │ │
│  │                │                                             │ │
│  └────────────────┼─────────────────────────────────────────────┘ │
│                   │                                               │
└───────────────────┼───────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         FINAL ANSWER                                │
└─────────────────────────────────────────────────────────────────────┘
```

The summary of the agentic flow. First of all profile of the agent is loaded, where agent description, strategy in which planning mode, max steps and other important features of the agent are defined. Then the mcp servers are initialised, all the mcp servers configs, tool maps and tools are stored in MultiMCP and it is initialized, upon MultiMCP initialization  all mcp sessions are initialized, tool info are loaded in server_tools and now these are now added as capabilities of the agent. Then once we enter our query, we do initial validation so that we dont pass any invalid input, or pass some credentials or unwanted input. Then AgentContext is initialized, with user_input, mcp_servers and AgentLoop is initialized and we run the agentLoop. The agent.run() call is within a infinity loop, but we keep a track of total steps, and profiles.yaml file has the max_step defined. In the agentloop.run(), first perception runs, which extracts the intent, entities, tool_hint, tags, and selected_srvers on the basis of the user query in the first step and depending upon tool results in the next steps. Depending on the perception output, we select the mcp server and summarize the tools, if no tools are selected then we tell the agent to get the planning mode and exploration mode from prompt path, then we pass these details to generate_plan() which takes the current query, perception output, memory_items which are initialied with initialization of AgentContext, it has all the memory of the current session, tool_description, prompt_path and steps. generate_plan() in decision generates full solve() function plan for the agent. It loads the prompt, tool description and the query to call llm using model.generate_text(prompt) and returns the plan to agentLoop, then the python_sandbox in action.py is run in which the solve() method is passed as code, plan is validated using heuristics, then tool call happens, and heuristics are used to validate the tool calls. Then depending upon the result of the python sandbox, we decide the next step. If it returns FINAL_ANSWER, then we return final answer, save to memory_items and update status of sove_sandbox as true. if its FURTHER_PROCESSING_REQUIRED, in user_input_override, we store, the original task, last tool call information and further instructions and continue the loop till we reach final answer or go out of max steps. 