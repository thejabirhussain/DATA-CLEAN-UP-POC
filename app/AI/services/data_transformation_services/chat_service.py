import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
from .code_executor_service import CodeExecutorService
from .dataframe_state_service import DataFrameStateService

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:8b"

AVAILABLE_TOOLS = """AVAILABLE TOOLS:
1. get_column_info() - Returns column names with dtypes
2. get_sample_data(columns: list) - Returns sample values for specified columns
3. get_dataframe_shape() - Returns shape and basic info about the dataframe

To use a tool, include it in the tools array:
{"tools": [{"tool": "get_column_info", "params": {}}]}
"""

SYSTEM_INSTRUCTIONS = f"""You are a DataFrame transformation assistant.

{AVAILABLE_TOOLS}

You must respond with valid JSON in this exact format:

{{
  "tools": [list of tools to call] | null,
  "code": "python code to execute" | null,
  "tasks_completed": true/false,
  "message": "final response to user" | null
}}

WORKFLOW:
1. Execute ONE transformation at a time on dataframe 'df' directly
2. ONLY use tools when you encounter errors to debug the issue
3. When ALL tasks are complete, set tasks_completed=true and provide final message
4. Do NOT use tools proactively - only for error debugging

ENVIRONMENT:
- Available modules: pandas (pd), numpy (np), datetime, re
- Work directly on dataframe 'df' - do NOT import modules or create new variables

RULES:
1. Execute ONLY ONE transformation per code block
2. Use tools when you need to understand the data structure or debug errors
3. STICK TO THE ORIGINAL REQUEST - Do not add extra transformations
4. message must be null until ALL tasks from the original request are completed
5. After successful code execution, respond with tasks_completed=true, code=null, and final message

EXAMPLES:

User: "Remove the ID column"
{{
  "tools": null,
  "code": "df = df.drop(columns=['ID'])",
  "tasks_completed": false,
  "message": null
}}
[You get: "Code executed successfully"]
{{
  "tools": null,
  "code": null,
  "tasks_completed": true,
  "message": "Done! Removed the ID column."
}}

User: "Make name column lowercase" (encounters error)
{{
  "tools": null,
  "code": "df['name'] = df['name'].str.lower()",
  "tasks_completed": false,
  "message": null
}}
[You get error: AttributeError: 'float' object has no attribute 'str']
{{
  "tools": [{{"tool": "get_sample_data", "params": {{"columns": ["name"]}}}}],
  "code": null,
  "tasks_completed": false,
  "message": null
}}
[You get sample data showing it's float values]
{{
  "tools": null,
  "code": "df['name'] = df['name'].astype(str).str.lower()",
  "tasks_completed": false,
  "message": null
}}
[You get: "Code executed successfully"]
{{
  "tools": null,
  "code": null,
  "tasks_completed": true,
  "message": "Done! Made name column lowercase."
}}

CRITICAL: Use tools to understand data structure and debug errors. Execute one transformation at a time. message must be null until ALL tasks are complete!
"""

code_executor = CodeExecutorService()


def format_ollama_conversation(conversation: List[Dict[str, str]]) -> str:
    """Convert conversation history to Ollama prompt format"""
    prompt = ""
    for msg in conversation:
        if msg["role"] == "system":
            prompt += msg["content"] + "\n\n"
        elif msg["role"] == "user":
            prompt += f"USER: {msg['content']}\n"
        elif msg["role"] == "assistant":
            prompt += f"ASSISTANT: {msg['content']}\n"
    prompt += "ASSISTANT:"
    return prompt


def log_final_conversation_summary(ollama_conversation: Optional[List[Dict[str, str]]]):
    """Write the final clean conversation summary to the file"""
    with open("storage/conversation_log.txt", "w", encoding="utf-8") as log_file:
        log_file.write(f"\n{'='*80}\n")
        log_file.write(f"FINAL CONVERSATION SUMMARY\n")
        log_file.write(f"{'='*80}\n\n")
        
        # Collect all executed code blocks
        all_code_blocks = []
        
        if ollama_conversation:
            for i, msg in enumerate(ollama_conversation, 1):
                role = msg["role"].upper()
                content = msg["content"]
                
                if msg["role"] == "system":
                    log_file.write(f"SYSTEM INSTRUCTIONS:\n{content}\n\n")
                elif msg["role"] == "user":
                    log_file.write(f"USER:\n{content}\n\n")
                else:  # assistant
                    # Count only assistant turns
                    assistant_turn = sum(1 for m in ollama_conversation[:i] if m["role"] == "assistant")
                    log_file.write(f"LLM TURN {assistant_turn}:\n{content}\n\n")
                
                # Extract code from JSON responses
                if msg["role"] == "assistant":
                    json_resp = extract_json_response(content)
                    if json_resp and json_resp.get("code"):
                        all_code_blocks.append(json_resp["code"])
        
        log_file.write(f"{'='*80}\n")
        log_file.write(f"CONVERSATION COMPLETED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*80}\n")
        
        # Append consolidated code section
        if all_code_blocks:
            log_file.write(f"\n{'='*80}\n")
            log_file.write(f"ALL EXECUTED CODE (CONSOLIDATED)\n")
            log_file.write(f"{'='*80}\n\n")
            log_file.write("```python\n")
            for i, code in enumerate(all_code_blocks, 1):
                log_file.write(f"# Step {i}\n")
                log_file.write(f"{code}\n\n")
            log_file.write("```\n")
            log_file.write(f"\n{'='*80}\n")
            log_file.write(f"TOTAL CODE BLOCKS EXECUTED: {len(all_code_blocks)}\n")
            log_file.write(f"{'='*80}\n")




def get_column_info(df_state: DataFrameStateService) -> str:
    if not df_state.has_dataframe():
        return "No dataframe available"
    
    df = df_state.get_dataframe()
    info = []
    for col in df.columns:
        info.append(f"{col}: {df[col].dtype}")
    return "Columns and types:\n" + "\n".join(info)

def get_sample_data(df_state: DataFrameStateService, columns: list) -> str:
    if not df_state.has_dataframe():
        return "No dataframe available"
    
    df = df_state.get_dataframe()
    result = []
    for col in columns:
        if col in df.columns:
            sample_values = df[col].head(5).tolist()
            result.append(f"{col}: {sample_values}")
        else:
            result.append(f"{col}: Column not found")
    return "Sample data:\n" + "\n".join(result)

def get_dataframe_shape(df_state: DataFrameStateService) -> str:
    if not df_state.has_dataframe():
        return "No dataframe available"
    
    df = df_state.get_dataframe()
    return f"Shape: {df.shape}, Columns: {len(df.columns)}, Rows: {len(df)}"


def execute_tools(tools: list, df_state: DataFrameStateService) -> str:
    results = []
    for tool_call in tools:
        tool_name = tool_call.get("tool")
        params = tool_call.get("params", {})
        
        if tool_name == "get_column_info":
            result = get_column_info(df_state)
        elif tool_name == "get_sample_data":
            columns = params.get("columns", [])
            result = get_sample_data(df_state, columns)
        elif tool_name == "get_dataframe_shape":
            result = get_dataframe_shape(df_state)
        else:
            result = f"Unknown tool: {tool_name}"
        
        results.append(result)
    
    return "\n\n".join(results)

def extract_json_response(response: str) -> Optional[Dict[str, Any]]:
    """Extract JSON response from LLM output"""
    import json
    
    # Try to find JSON in the response
    start = response.find("{")
    if start == -1:
        return None
    
    # Find the matching closing brace
    brace_count = 0
    end = start
    for i, char in enumerate(response[start:], start):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break
    
    try:
        json_str = response[start:end]
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def execute_code(code: str, df_state: DataFrameStateService) -> tuple[bool, Optional[str]]:
    if not code:
        return False, "No code provided"

    if not df_state.has_dataframe():
        return False, "No dataframe available"

    result_df, output_msg, error_msg = code_executor.execute_code(
        code, df_state.get_dataframe()
    )

    if error_msg:
        return False, error_msg

    df_state.update_dataframe(result_df)
    
    # Always save to data.csv after successful code execution
    try:
        df_state.get_dataframe().to_csv('storage/data.csv', index=False)
        print(f"✓ Data saved to data.csv - Shape: {df_state.get_dataframe().shape}")
    except Exception as e:
        print(f"⚠ Warning: Could not save to data.csv: {e}")
    
    return True, output_msg




def chat(message: str, conversation_history: List[Dict], df_state: DataFrameStateService) -> Dict[str, Any]:
    if not df_state.has_dataframe():
        return {
            "message": "No dataframe available. Please upload a file first.",
            "has_code": False,
        }

    max_turns = 5
    turn_count = 0
    current_message = message
    
    ollama_conversation = []
    gemini_chat = None  # Will be initialized if using Gemini

    while turn_count < max_turns:
        print(f"\n====================")

        if turn_count == 0:
            df_info = f"""
        DATAFRAME INFO:
        Columns: {df_state.get_dataframe().columns.tolist()}
        Shape: {df_state.get_dataframe().shape}
        Data Types: {df_state.get_dataframe().dtypes.to_dict()}
        Sample Data:
        {df_state.get_dataframe().head().to_string()}
        """
            ollama_conversation = [
                {"role": "system", "content": f"{SYSTEM_INSTRUCTIONS}\n{df_info}"},
                {"role": "user", "content": current_message}
            ]
        else:
            ollama_conversation.append({"role": "user", "content": current_message})
        
        # OLLAMA API CALL
        prompt = format_ollama_conversation(ollama_conversation)
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 400},
            },
        ).json()
        llm_response = response.get("response", "")
        
        turn_count += 1
        print(f"\n========== LLM TURN {turn_count} ==========")
        
        ollama_conversation.append({"role": "assistant", "content": llm_response})
        print(f"LLM Response: {llm_response}")

        json_response = extract_json_response(llm_response)
        if not json_response:
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = "Please respond with valid JSON format as specified."
            continue

        if json_response.get("tasks_completed", False):
            final_message = json_response.get("message", "Task completed")
            print(f"All tasks completed: {final_message}")
            
            log_final_conversation_summary(ollama_conversation)
            
            return {
                "message": final_message,
                "has_code": True,
                "raw_response": llm_response,
            }

        tools = json_response.get("tools")
        code = json_response.get("code")
        
        if tools:
            print(f"Executing tools: {tools}")
            tool_results = execute_tools(tools, df_state)
            print(f"Tool results: {tool_results}")
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "tools": tools,
                    "tool_results": tool_results,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = f"Tool results:\n{tool_results}"
            continue
        
        if not code:
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = "Please provide code or tools in the JSON response."
            continue

        print(f"Executing code:\n{code}")
        success, output = execute_code(code, df_state)

        if success:
            print(f"Success: {output}")
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "code": code,
                    "output": output,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = f"Code executed successfully. Output:\n{output}"
        else:
            print(f"Failed: {output}")
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "code": code,
                    "error": output,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = f"Code failed with error:\n{output}\n\nFix it and try again."

    print(f"Max turns ({max_turns}) reached")
    
    # Log final conversation summary
    log_final_conversation_summary(ollama_conversation)
    
    return {
        "message": "Task execution stopped - maximum turns reached.",
        "has_code": False,
        "raw_response": "Max turns reached",
    }

def chat_gemini(message: str, conversation_history: List[Dict], df_state: DataFrameStateService) -> Dict[str, Any]:
    """Chat function using Gemini model"""
    if not df_state.has_dataframe():
        return {
            "message": "No dataframe available. Please upload a file first.",
            "has_code": False,
        }

    from .gemini_chat_service import GeminiChatService
    
    max_turns = 5
    turn_count = 0
    current_message = message
    
    gemini_chat = None
    gemini_conversation = []

    while turn_count < max_turns:
        print(f"\n====================")

        if turn_count == 0:
            df_info = f"""
        DATAFRAME INFO:
        Columns: {df_state.get_dataframe().columns.tolist()}
        Shape: {df_state.get_dataframe().shape}
        Data Types: {df_state.get_dataframe().dtypes.to_dict()}
        Sample Data:
        {df_state.get_dataframe().head().to_string()}
        """
            gemini_chat = GeminiChatService()
            system_instruction = SYSTEM_INSTRUCTIONS + f"\n{df_info}"
            gemini_chat.set_system_instruction(system_instruction)
            llm_response = gemini_chat.send_message(current_message)
            
            gemini_conversation = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": current_message}
            ]
        else:
            llm_response = gemini_chat.send_message(current_message)
            gemini_conversation.append({"role": "user", "content": current_message})
        
        turn_count += 1
        print(f"\n========== LLM TURN {turn_count} ==========")
        
        gemini_conversation.append({"role": "assistant", "content": llm_response})
        print(f"LLM Response: {llm_response}")

        json_response = extract_json_response(llm_response)
        if not json_response:
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = "Please respond with valid JSON format as specified."
            continue

        if json_response.get("tasks_completed", False):
            final_message = json_response.get("message", "Task completed")
            print(f"All tasks completed: {final_message}")
            
            log_final_conversation_summary(gemini_conversation)
            
            return {
                "message": final_message,
                "has_code": True,
                "raw_response": llm_response,
            }

        tools = json_response.get("tools")
        code = json_response.get("code")
        
        if tools:
            print(f"Executing tools: {tools}")
            tool_results = execute_tools(tools, df_state)
            print(f"Tool results: {tool_results}")
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "tools": tools,
                    "tool_results": tool_results,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = f"Tool results:\n{tool_results}"
            continue
        
        if not code:
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = "Please provide code or tools in the JSON response."
            continue

        print(f"Executing code:\n{code}")
        success, output = execute_code(code, df_state)

        if success:
            print(f"Success: {output}")
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "code": code,
                    "output": output,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = f"Code executed successfully. Output:\n{output}"
        else:
            print(f"Failed: {output}")
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "code": code,
                    "error": output,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = f"Code failed with error:\n{output}\n\nFix it and try again."

    print(f"Max turns ({max_turns}) reached")
    
    # Log final conversation summary
    log_final_conversation_summary(gemini_conversation)
    
    return {
        "message": "Task execution stopped - maximum turns reached.",
        "has_code": False,
        "raw_response": "Max turns reached",
    }