import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
from code_executor import CodeExecutor
from dataframe_state import DataFrameState


OLLAMA_URL = "http://localhost:11434/api/generate"
# OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_MODEL = "qwen3-coder:30b"  # Try this model

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
4. Use print statements to validate each transformation
5. Only use <exit>message</exit> when ALL tasks are complete
6. ALWAYS REMEMBER THE ORIGINAL USER REQUEST - Never forget what the user asked you to do. Stay focused on completing those specific tasks.

CODE EXECUTION:
- Wrap code in ```python blocks
- Common modules (pandas as pd, numpy as np, re) are already imported
- All changes must be made on the existing 'df' object
- You can import additional modules as needed

WORKFLOW:
1. Inspect the data (print columns, shape, head)
2. Execute one transformation
3. Print validation to see the result
4. Wait for output in next turn
5. Continue with next transformation
6. Repeat until all tasks done
7. Use <exit> tag when finished

EXAMPLES:

Simple task:
User: "Remove the ID column"

Turn 1: "Let me check the dataframe structure."
```python
print(df.columns.tolist())
print(df.head())
```

Turn 2 (after seeing output): "Now removing the ID column."
```python
df = df.drop(columns=['ID'])
print(f"Columns after drop: {df.columns.tolist()}")
```
<exit>ID column removed successfully!</exit>

Complex task:
User: "1) Remove ID 2) Clean names 3) Sort by amount"

Turn 1: "Inspecting the data first."
```python
print(df.columns.tolist())
print(df.head())
```

Turn 2 (after seeing output): "Removing ID column."
```python
df = df.drop(columns=['ID'])
print(f"Shape: {df.shape}")
```

Turn 3 (after seeing output): "Cleaning names."
```python
df['Name'] = df['Name'].str.strip().str.title()
print(df['Name'].head())
```

Turn 4 (after seeing output): "Sorting by amount."
```python
df = df.sort_values('Amount', ascending=False)
print(df.head())
```
<exit>All tasks completed!</exit>
"""

code_executor = CodeExecutor()


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
    return True, output_msg




async def chat(message: str, conversation_history: List[Dict], df_state: DataFrameState) -> Dict[str, Any]:
    if not df_state.has_dataframe():
        return {
            "message": "No dataframe available. Please upload a file first.",
            "has_code": False,
        }

    max_turns = 15
    turn_count = 0
    current_message = message  # Track the current message to send
    
    with open("conversation_log.txt", "w", encoding="utf-8") as log_file:
        log_file.write(f"{'='*80}\n")
        log_file.write(f"NEW CHAT SESSION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"{'='*80}\n\n")

    while turn_count < max_turns:
        turn_count += 1
        print(f"\n========== TURN {turn_count} ==========")

        if turn_count == 1:
            # First turn: Send system instructions + DataFrame info + original user message
            df_info = f"""
DATAFRAME INFO:
Columns: {df_state.get_dataframe().columns.tolist()}
Shape: {df_state.get_dataframe().shape}
Data Types: {df_state.get_dataframe().dtypes.to_dict()}
Sample Data:
{df_state.get_dataframe().head().to_string()}
"""
            prompt = f"{SYSTEM_INSTRUCTIONS}\n{df_info}\nUSER: {current_message}\nASSISTANT:"
        else:
            # Subsequent turns: Only send the execution result
            prompt = f"USER: {current_message}\nASSISTANT:"
        
        with open("conversation_log.txt", "a", encoding="utf-8") as log_file:
            log_file.write(f"\n{'='*80}\n")
            log_file.write(f"TURN {turn_count} - INPUT TO LLM\n")
            log_file.write(f"{'='*80}\n")
            log_file.write(prompt)
            log_file.write(f"\n\n")

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
        print(f"LLM Response: {llm_response}")
        
        with open("conversation_log.txt", "a", encoding="utf-8") as log_file:
            log_file.write(f"{'='*80}\n")
            log_file.write(f"TURN {turn_count} - OUTPUT FROM LLM\n")
            log_file.write(f"{'='*80}\n")
            log_file.write(llm_response)
            log_file.write(f"\n\n")

        exit_message = extract_exit_message(llm_response)
        if exit_message:
            print(f"Exit detected: {exit_message}")
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
    return {
        "message": "Task execution stopped - maximum turns reached.",
        "has_code": False,
        "raw_response": "Max turns reached",
    }
