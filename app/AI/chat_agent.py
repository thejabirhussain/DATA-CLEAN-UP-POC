import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
from code_executor import CodeExecutor
from dataframe_state import DataFrameState

# Ollama configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:8b"

SYSTEM_INSTRUCTIONS = """You are an Excel transformer. Your task is to execute Python code to manipulate the given dataframe 'df'.

HOW THIS WORKS - ITERATIVE EXECUTION:
- You are in a LOOP that continues across multiple turns
- Write ONE code block per response
- After you respond, your code will be executed
- You will receive the output/result in the next turn
- Based on that result, you decide the next step
- Control stays with you until you use the <exit> tag

IMPORTANT RULES:
1. Write ONLY ONE ```python code block per response
2. Do NOT try to complete all tasks in one turn
3. Wait to see execution results before proceeding
4. Use minimal print statements - only for initial data inspection or final verification
5. Use <exit>SUMMARY: [What you accomplished] - Original request: [user's original message]</exit> when ALL tasks are complete
6. ALWAYS REMEMBER THE ORIGINAL USER REQUEST - Never forget what the user asked you to do. Stay focused on completing those specific tasks.
7. COMPLETE THE TASK AND EXIT - Do not perform additional transformations unless specifically requested. Use <exit> immediately after completing the user's request.

CODE EXECUTION:
- Wrap code in ```python blocks
- Common modules (pandas as pd, numpy as np, re) are already imported
- All changes must be made on the existing 'df' object
- You can import additional modules as needed

WORKFLOW:
1. If needed, briefly inspect the data structure
2. Execute the requested transformation
3. Use <exit> when the specific task is complete
4. Do NOT explore or modify data beyond what was requested

EXAMPLES:

Simple task:
User: "Remove the ID column"

Turn 1: "Removing the ID column."
```python
df = df.drop(columns=['ID'])
print(f"Removed ID column. New shape: {df.shape}")
```
<exit>SUMMARY: Successfully removed the ID column from the dataframe. Original request: Remove the ID column</exit>

Complex task:
User: "1) Remove ID 2) Clean names 3) Sort by amount"

Turn 1: "Removing ID column."
```python
df = df.drop(columns=['ID'])
print(f"Shape after removing ID: {df.shape}")
```

Turn 2: "Cleaning names."
```python
df['Name'] = df['Name'].str.strip().str.title()
```

Turn 3: "Sorting by amount."
```python
df = df.sort_values('Amount', ascending=False)
print(f"Sorted by amount. Top value: {df['Amount'].iloc[0]}")
```
<exit>SUMMARY: Completed all 3 tasks - removed ID column, cleaned names with proper formatting, and sorted by amount in descending order. Original request: 1) Remove ID 2) Clean names 3) Sort by amount</exit>
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
                    log_file.write(f"USER REQUEST:\n{content}\n\n")
                else:  # assistant
                    # Count only assistant turns
                    assistant_turn = sum(1 for m in ollama_conversation[:i] if m["role"] == "assistant")
                    log_file.write(f"LLM TURN {assistant_turn}:\n{content}\n\n")
                
                # Extract code blocks from assistant messages
                if msg["role"] == "assistant":
                    code_block = extract_code_block(content)
                    if code_block:
                        all_code_blocks.append(code_block)
        
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


def extract_code_block(response: str) -> Optional[str]:

    start = response.find("```python")
    if start == -1:
        return None

    start += len("```python")
    end = response.find("```", start)
    if end == -1:
        return None

    code_block = response[start:end].strip()
    return code_block if code_block else None


def extract_exit_message(response: str) -> Optional[str]:
    start = response.find("<exit>")
    if start == -1:
        return None

    start += len("<exit>")
    end = response.find("</exit>", start)
    if end == -1:
        return None

    return response[start:end].strip()


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

    max_turns = 15
    turn_count = 0
    current_message = message  # Track the current message to send
    
    # Initialize Ollama conversation history
    ollama_conversation = []
    
    # We'll write the final conversation summary at the end, not during the process

    while turn_count < max_turns:
        print(f"\n========== PREPARING LLM REQUEST ==========")

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

        exit_message = extract_exit_message(llm_response)
        if exit_message:
            print(f"Exit detected: {exit_message}")
            
            # Log final conversation summary
            log_final_conversation_summary(ollama_conversation)
            
            return {
                "message": exit_message,
                "has_code": True,
                "raw_response": llm_response,
            }

        code = extract_code_block(llm_response)
        if not code:
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": llm_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            current_message = "Continue with the task."
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
            current_message = f"Code executed successfully. Output:\n{output}\n\nContinue."
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
