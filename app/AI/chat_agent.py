import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
from code_executor import CodeExecutor
from dataframe_state import DataFrameState

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:8b"
#qwen3-coder:30b
#llama3.1:8b
#deepseek-r1:14b

SYSTEM_INSTRUCTIONS = """You are an Excel data transformer. Execute Python code to modify the dataframe 'df'.

You must respond with valid JSON in this exact format:

{
  "tasks_completed": true/false,
  "code": "python code to execute",
  "message": null | "final response to user's original query"
}

HOW IT WORKS:
- Execute ONE transformation at a time
- The code execution result will be fed back to you
- When ALL tasks are complete, set tasks_completed=true and provide final message
- message must be null until ALL tasks are completed

ENVIRONMENT:
- Available modules: pandas (pd), numpy (np), datetime, re
- Work directly on dataframe 'df' - do NOT import modules or create new variables

RULES:
1. Execute ONLY ONE transformation per code block
2. Do NOT add print statements unless debugging errors
3. If you encounter an error, print dtype and sample values of the problematic column
4. STICK TO THE ORIGINAL REQUEST - Do not add extra transformations
5. message must be null until ALL tasks from the original request are completed
6. After successful code execution, respond with tasks_completed=true, code=null, and final message

EXAMPLES:

User: "Remove the ID column"
{
  "tasks_completed": false,
  "code": "df = df.drop(columns=['ID'])",
  "message": null
}
[You get: "Code executed successfully. Output: None"]
{
  "tasks_completed": true,
  "code": null,
  "message": "Done! Removed the ID column."
}

User: "Remove A column and rename B to C"
Turn 1:
{
  "tasks_completed": false,
  "code": "df = df.drop(columns=['A'])",
  "message": null
}
[You get: "Code executed successfully. Output: None"]
Turn 2:
{
  "tasks_completed": false,
  "code": "df = df.rename(columns={'B': 'C'})",
  "message": null
}
[You get: "Code executed successfully. Output: None"]
Turn 3:
{
  "tasks_completed": true,
  "code": null,
  "message": "Done! Removed A column and renamed B to C."
}

User: "Make name column lowercase"  
{
  "tasks_completed": false,
  "code": "df['name'] = df['name'].str.lower()",
  "message": null
}
[You get error about float not having str attribute]
{
  "tasks_completed": false,
  "code": "print(f'Column dtype: {df[\"name\"].dtype}'); print(f'Sample values: {df[\"name\"].head()}')",
  "message": null
}
[You get debug info showing it's float]
{
  "tasks_completed": false,
  "code": "df['name'] = df['name'].astype(str).str.lower()",
  "message": null
}
[You get: "Code executed successfully. Output: None"]
{
  "tasks_completed": true,
  "code": null,
  "message": "Done! Made name column lowercase."
}

CRITICAL: STICK TO THE ORIGINAL REQUEST ONLY! No print statements unless debugging errors. message must be null until ALL tasks are complete!
"""

code_executor = CodeExecutor()


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
    with open("conversation_log.txt", "w", encoding="utf-8") as log_file:
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


def execute_code(code: str, df_state: DataFrameState) -> tuple[bool, Optional[str]]:
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
        df_state.get_dataframe().to_csv('data.csv', index=False)
        print(f"✓ Data saved to data.csv - Shape: {df_state.get_dataframe().shape}")
    except Exception as e:
        print(f"⚠ Warning: Could not save to data.csv: {e}")
    
    return True, output_msg




def chat(message: str, conversation_history: List[Dict], df_state: DataFrameState) -> Dict[str, Any]:
    if not df_state.has_dataframe():
        return {
            "message": "No dataframe available. Please upload a file first.",
            "has_code": False,
        }

    max_turns = 5
    turn_count = 0
    current_message = message  # Track the current message to send
    
    # Initialize Ollama conversation history
    ollama_conversation = []
    
    # We'll write the final conversation summary at the end, not during the process

    while turn_count < max_turns:
        print(f"\n====================")

        # Ollama: Build full conversation history
        if turn_count == 0:
            df_info = f"""
DATAFRAME INFO:
Columns: {df_state.get_dataframe().columns.tolist()}
Shape: {df_state.get_dataframe().shape}
Data Types: {df_state.get_dataframe().dtypes.to_dict()}
Sample Data:
{df_state.get_dataframe().head().to_string()}
"""
            # Initialize conversation with system + user message
            ollama_conversation = [
                {"role": "system", "content": f"{SYSTEM_INSTRUCTIONS}\n{df_info}"},
                {"role": "user", "content": current_message}
            ]
        else:
            # Add new user message to conversation
            ollama_conversation.append({"role": "user", "content": current_message})
        
        # Convert conversation to Ollama prompt format
        prompt = format_ollama_conversation(ollama_conversation)


        # Ollama API call with full conversation history
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
        
        # Increment turn count only when LLM responds
        turn_count += 1
        print(f"\n========== LLM TURN {turn_count} ==========")
        
        # Add assistant response to Ollama conversation history
        ollama_conversation.append({"role": "assistant", "content": llm_response})
        print(f"LLM Response: {llm_response}")

        # Parse JSON response
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

        # Check if all tasks are completed
        if json_response.get("tasks_completed", False):
            final_message = json_response.get("message", "Task completed")
            print(f"All tasks completed: {final_message}")
            
            # Log final conversation summary
            log_final_conversation_summary(ollama_conversation)
            
            return {
                "message": final_message,
                "has_code": True,
                "raw_response": llm_response,
            }

        # Extract code from JSON
        code = json_response.get("code")
        
        if not code:
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = "Please provide code in the JSON response."
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
