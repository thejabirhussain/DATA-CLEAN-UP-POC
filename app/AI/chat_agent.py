import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
from code_executor import CodeExecutor

class ConversationState:
    def __init__(self):
        self.messages = []
        self.dataframe = None
        self.dataframe_history = []

class ChatAgent:
    def __init__(self, websocket=None):
        self.ollama_url = "http://localhost:11434/api/generate" 
        #qwen3-coder:30b 
        self.ollama_model = "llama3.1:8b"
        self.code_executor = CodeExecutor()
        self.websocket = websocket
        
        # AUTONOMOUS EXECUTION FEATURE FLAG - Comment this line to disable
        self.ENABLE_AUTONOMOUS_EXECUTION = True
    
    async def _emit_dataframe_update(self, df: pd.DataFrame):
        """Emit simple refresh event to WebSocket client"""
        print(f"🔄 _emit_dataframe_update called - WebSocket: {self.websocket is not None}, DF: {df is not None}")
        
        if self.websocket and df is not None:
            try:
                import json
                
                message = {
                    "type": "dataframe_refresh",
                    "data": {
                        "message": "Dataframe updated - please refresh"
                    }
                }
                
                print(f"📤 Sending WebSocket refresh event")
                await self.websocket.send_text(json.dumps(message))
                print(f"✅ WebSocket refresh event sent successfully")
                
            except Exception as e:
                print(f"❌ WebSocket emission error: {str(e)}")
        else:
            if not self.websocket:
                print(f"⚠️ No WebSocket connection available")
            if df is None:
                print(f"⚠️ DataFrame is None")
        
    async def _get_model_response(self, context: str, message: str, model_type: str = "ollama") -> str:
        full_prompt = f"{context}\n\nUSER: {message}\nASSISTANT:"
        try:
            response = requests.post(self.ollama_url, json={
                "model": self.ollama_model,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                "num_predict": 600
                }
            })
            
            result = response.json()
            raw_text = result.get("response")
            return raw_text
            
        except Exception as e:
            return f"Error in '_get_model_response': {str(e)}"
    
    
    async def chat(self, message: str, conversation_history: List[Dict], df: pd.DataFrame = None, model_type: str = "ollama") -> Dict:
        print(f"USER: {message}")
        
        # AUTONOMOUS EXECUTION - Comment these 3 lines to disable
        if hasattr(self, 'ENABLE_AUTONOMOUS_EXECUTION') and self._is_multiple_tasks(message):
            return await self._autonomous_chat(message, conversation_history, df, model_type)
        
        context = self._build_conversation_context(conversation_history, df)
        
        response = await self._get_model_response(context, message, model_type)
        print("------------- MODEL RESPONSE -------------")
        print(response)
        
        if self._contains_code_execution(response):
            code = self._extract_code_from_response(response)
            print("------------- CODE EXECUTED -------------")
            print(code)
            execution_result = self._execute_code(code, df)
            user_message = self._extract_user_message_from_response(response)
            
            retry_count = 0
            max_retries = 5
            current_result = execution_result
            current_response = response
            current_code = code
            current_user_message = user_message
            
            while not current_result.get('success', False) and retry_count < max_retries:
                retry_count += 1
                print(f"------------- RETRY ATTEMPT {retry_count}/{max_retries} -------------")
                
                try:
                    error_msg = current_result['error']
                    print(f"EXECUTION ERROR: {error_msg}")
                except KeyError as e:
                    error_msg = f"Error in 'chat()': execution_result missing 'error' key. Keys: {list(current_result.keys())} - {str(e)}"
                    print(f"EXECUTION ERROR: {error_msg}")
                
                conversation_history.append({
                    'role': 'assistant',
                    'content': current_response,
                    'code': current_code,
                    'timestamp': datetime.now().isoformat()
                })
                
                error_feedback = f"I ran into an error executing your code. Here's the error:\n\n{error_msg}\n\nPlease fix the code and try again. Make sure to check the data types and column names."
                conversation_history.append({
                    'role': 'user', 
                    'content': error_feedback,
                    'timestamp': datetime.now().isoformat()
                })
                
                retry_context = self._build_conversation_context(conversation_history, df)
                retry_response = await self._get_model_response(retry_context, error_feedback)
                print("------------- RETRY RESPONSE -------------")
                print(retry_response)
                
                if self._contains_code_execution(retry_response):
                    retry_code = self._extract_code_from_response(retry_response)
                    print("------------- RETRY CODE EXECUTED -------------")
                    print(retry_code)
                    retry_execution_result = self._execute_code(retry_code, df)
                    retry_user_message = self._extract_user_message_from_response(retry_response)
                    
                    current_result = retry_execution_result
                    current_response = retry_response
                    current_code = retry_code
                    current_user_message = retry_user_message
                else:
                    return {
                        'message': retry_response,
                        'has_code': False,
                        'raw_response': retry_response,
                        'retry_attempt': True,
                        'retry_count': retry_count
                    }
            
            if not current_result.get('success', False):
                try:
                    final_error_msg = current_result['error']
                    print(f"FINAL ERROR AFTER {retry_count} RETRIES: {final_error_msg}")
                except KeyError as e:
                    final_error_msg = f"Error in 'chat()': final result missing 'error' key. Keys: {list(current_result.keys())} - {str(e)}"
                    print(f"FINAL ERROR AFTER {retry_count} RETRIES: {final_error_msg}")
            
            return {
                'message': current_user_message,
                'has_code': True,
                'execution_result': current_result,
                'raw_response': current_response,
                'executed_code': current_code,
                'retry_attempt': retry_count > 0,
                'retry_count': retry_count
            }
        else:
            return {
                'message': response,
                'has_code': False,
                'raw_response': response,
            }
            
    def _build_conversation_context(self, history: List[Dict], df: pd.DataFrame) -> str:
        df_info = self._get_dataframe_info(df) if df is not None else "No data loaded"
        
        system_prompt = f"""You are a friendly data assistant. Be conversational and helpful.

DATA INFO:
{df_info}

IMPORTANT RULES:
- Look at the current column names and data state before writing code
- Only perform operations that are actually needed
- If a column already exists with the right name, don't rename it again
- If data is already in the right format, don't transform it again
- Check the current state first, then do only what's missing
- The DataFrame is available as variable 'df' - this contains the user's data
- Common modules are pre-imported: pandas (as pd), numpy (as np), re, datetime
- You can import additional modules if needed (except os, subprocess, shutil for security)

RESPONSE STYLE:
- Start with a friendly acknowledgment like "Sure!" or "I'll help you with that"
- Give a brief, simple explanation of what you're doing
- Keep responses short and user-friendly
- Use <execute_code> tags for data transformations

EXAMPLES:

User: "Rename Ledger Name to Ledger"
Response: "Sure! I'll rename that column for you."
<execute_code>
df = df.rename(columns={{'Ledger Name': 'Ledger'}})
</execute_code>

User: "Move Ledger column to the front" (when Ledger column already exists)
Response: "I'll move the Ledger column to the front for you."
<execute_code>
cols = ['Ledger'] + [col for col in df.columns if col != 'Ledger']
df = df[cols]
</execute_code>

User: "Clean the email column"
Response: "What kind of cleaning do you need? Remove spaces, fix formatting, or something else?"

CONVERSATION HISTORY:
"""
        
        recent_history = history[-10:] if len(history) > 10 else history
        for msg in recent_history:
            role = msg['role'].upper()
            content = msg['content']
            system_prompt += f"\n{role}: {content}"
            if msg.get('code'):
                system_prompt += f"\n[EXECUTED CODE: {msg['code']}]"
        
        return system_prompt
    
    def _contains_code_execution(self, response: str) -> bool:
        return ("<execute_code>" in response and "</execute_code>" in response)
    
    def _extract_code_from_response(self, response: str) -> str:
        try:
            code_blocks = []
            start_pos = 0
            
            while True:
                start = response.find("<execute_code>", start_pos)
                if start == -1:
                    break
                    
                start += len("<execute_code>")
                end = response.find("</execute_code>", start)
                if end == -1:
                    break
                    
                code_block = response[start:end].strip()
                if code_block:
                    code_blocks.append(code_block)
                
                start_pos = end + len("</execute_code>")
            
            return "\n".join(code_blocks) if code_blocks else ""
        except Exception as e:
            return f"Error in '_extract_code_from_response': {str(e)}"
    
    def _extract_user_message_from_response(self, response: str) -> str:
        try:
            code_start = response.find("<execute_code>")
            if code_start != -1:
                return response[:code_start].strip()
            
            return response
        except Exception as e:
            return f"Error in '_extract_user_message_from_response': {str(e)}"

    def _execute_code(self, code: str, df: pd.DataFrame) -> Dict:
        if not code or df is None:
            return {'success': False, 'error': 'No code or dataframe provided'}
        
        try:
            result_df, execution_log = self.code_executor.execute_code(code, df)
            
            execution_failed = any(error_word in execution_log.lower() for error_word in 
                                 ['error:', 'failed', 'traceback', 'exception', 'keyerror'])
            
            if execution_failed:
                return {
                    'success': False,
                    'error': execution_log,
                    'dataframe': df
                }
            
            return {
                'success': True,
                'dataframe': result_df,
                'execution_log': execution_log,
                'original_shape': list(df.shape),
                'new_shape': list(result_df.shape)
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error in '_execute_code': {str(e)}",
                'dataframe': df
            }
    
    def _get_dataframe_info(self, df: pd.DataFrame) -> str:
        if df is None:
            return "No dataframe available"
        
        dtypes_dict = {}
        for col, dtype in df.dtypes.items():
            dtypes_dict[str(col)] = str(dtype)
        
        return f"""
- Shape: {df.shape}
- Columns: {list(df.columns)}
- Data types: {dtypes_dict}
- Sample data (first 3 rows):
{df.head(3).to_string()}
"""
    
    # ========== AUTONOMOUS EXECUTION METHODS ==========
    # Comment this entire section to disable autonomous execution
    
    def _is_multiple_tasks(self, message: str) -> bool:
        """Detect if message contains multiple numbered tasks"""
        import re
        numbered_tasks = re.findall(r'\d+\)', message)
        return len(numbered_tasks) > 1
    
    async def _autonomous_chat(self, message: str, conversation_history: List[Dict], df: pd.DataFrame = None, model_type: str = "ollama") -> Dict:
        """Handle autonomous execution for multiple tasks"""
        current_message = message
        current_df = df
        execution_turns = []
        turn_count = 0
        max_turns = 10  # Safety limit
        
        # Use the original conversation history and evolve it
        working_history = conversation_history
        
        while turn_count < max_turns:
            turn_count += 1
            print(f"========== AUTONOMOUS TURN {turn_count} ==========")
            
            context = self._build_autonomous_context(working_history, current_df)
            response = await self._get_model_response(context, current_message, model_type)
            print("------------- MODEL RESPONSE -------------")
            print(response)
        
            # Process this turn
            turn_result = await self._process_autonomous_turn(response, current_df, working_history)
            execution_turns.append(turn_result)
            
            # Update dataframe if execution was successful
            if turn_result.get('has_code') and turn_result.get('execution_result', {}).get('success'):
                current_df = turn_result['execution_result']['dataframe']
                print(f"🎯 Turn {turn_count}: Code executed successfully, saving to data.csv and emitting update...")
                
                # Save updated dataframe to CSV immediately
                try:
                    current_df.to_csv('data.csv', index=False)
                    print(f"💾 Dataframe saved to data.csv successfully")
                except Exception as e:
                    print(f"❌ Failed to save dataframe to CSV: {str(e)}")
                
                # Emit real-time dataframe update to WebSocket
                await self._emit_dataframe_update(current_df)
            else:
                print(f"⏭️ Turn {turn_count}: No code execution or execution failed, skipping dataframe update")
            
            # Add this turn to conversation history
            working_history.append({
                'role': 'assistant',
                'content': turn_result['message'],
                'code': turn_result.get('executed_code'),
                'timestamp': datetime.now().isoformat()
            })
            
            # Check if LLM wants to continue
            continue_action = self._extract_continue_action(response)
            if continue_action is None:
                # No continue tag found - LLM is done
                print(f"========== AUTONOMOUS EXECUTION COMPLETED AFTER {turn_count} TURNS ==========")
                return self._aggregate_autonomous_results(execution_turns, current_df, turn_count)
            
            # Prepare next message for continuation
            current_message = f"You are in autonomous execution mode. Complete this remaining task: {continue_action}. Do NOT repeat previous tasks that are already completed."
        
        # Safety limit reached
        print(f"========== AUTONOMOUS EXECUTION STOPPED - MAX TURNS ({max_turns}) REACHED ==========")
        return self._aggregate_autonomous_results(execution_turns, current_df, turn_count)
    
    def _build_task_aware_retry_context(self, history: List[Dict], df: pd.DataFrame, failed_response: str) -> str:
        """Build context for retry attempts that maintains task awareness"""
        df_info = self._get_dataframe_info(df) if df is not None else "No data loaded"
        
        # Extract the current task from the failed response
        current_task = "the current task"
        if "Continue with:" in failed_response:
            # This was a continuation from previous turn
            lines = failed_response.split('\n')
            for line in lines:
                if 'Continue with:' in line:
                    current_task = line.replace('Continue with:', '').strip()
                    break
        else:
            # Try to extract task from the response content
            if 'Split Period' in failed_response:
                current_task = "Split Period Column into Period Year and Period Month"
            elif 'standardize' in failed_response.lower() and 'header' in failed_response.lower():
                current_task = "Standardize column headers by removing Name suffix"
            elif 'sort' in failed_response.lower() or 'order' in failed_response.lower():
                current_task = "Order records by Net Amount in descending order"
        
        system_prompt = f"""You are an Excel transformer in RETRY MODE for autonomous execution.

DATA FRAME:
{df_info}

RETRY CONTEXT:
You were working on: {current_task}
Your code failed with an error. You need to FIX THE SPECIFIC CODE for this task only.

IMPORTANT:
- Focus ONLY on fixing the code for: {current_task}
- Do NOT work on other tasks or columns
- Do NOT repeat previous tasks
- Fix the specific error in your code for this task
- Use proper pandas syntax and column names

CONVERSATION HISTORY:
"""
        
        recent_history = history[-5:] if len(history) > 5 else history
        for msg in recent_history:
            role = msg['role'].upper()
            content = msg['content']
            system_prompt += f"\n{role}: {content}"
            if msg.get('code'):
                system_prompt += f"\n[EXECUTED CODE: {msg['code']}]"
        
        return system_prompt
    
    def _build_autonomous_context(self, history: List[Dict], df: pd.DataFrame) -> str:
        """Build context specifically for autonomous execution"""
        df_info = self._get_dataframe_info(df) if df is not None else "No data loaded"
        
        system_prompt = f"""You are an Excel transformer. You need to make data transformations for users.

DATA FRAME:
{df_info}

INSTRUCTIONS:
You need to make code changes by generating and wrapping code in <execute_code> tags, which will then be executed in a Python environment. Common modules like numpy (np), pandas (pd), re have already been imported. You can import any module you require as well, but changes need to be made on the existing 'df' object.

TASK CLASSIFICATION:
Once you get a user query, you need to understand the intent and classify it into the following categories:

SINGLE TASK:
If the user gives you one task or a simple request, handle it directly in one response.
Example:
User: "Remove the ID column"
Response: "I'll remove the ID column for you."
<execute_code>
df = df.drop(columns=['ID'])
</execute_code>

MULTIPLE TASKS:
If the user gives you multiple numbered tasks (like "1) Do X 2) Do Y 3) Do Z"), you MUST use autonomous execution to handle them one by one across multiple turns.

For multiple tasks:
- Do ONE task per turn
- After each task (except the last), use <continue_with>LIST ALL REMAINING TASKS</continue_with>
- Include ALL remaining task numbers and descriptions in the continue tag
- Only stop when all tasks are completed (no continue tag on final turn)

Example for multiple tasks:
User: "1) Delete ID column 2) Clean names 3) Sort by amount"

Turn 1: "I'll start by deleting the ID column."
<execute_code>
df = df.drop(columns=['ID'])
</execute_code>
<continue_with>2) Clean names 3) Sort by amount</continue_with>

Turn 2: "Now I'll clean the names."
<execute_code>
df['Name'] = df['Name'].str.strip().str.title()
</execute_code>
<continue_with>3) Sort by amount</continue_with>

Turn 3: "Finally, sorting by amount."
<execute_code>
df = df.sort_values('Amount', ascending=False)
</execute_code>
All tasks completed!

CONVERSATION HISTORY:
"""
        
        recent_history = history[-10:] if len(history) > 10 else history
        for msg in recent_history:
            role = msg['role'].upper()
            content = msg['content']
            system_prompt += f"\n{role}: {content}"
            if msg.get('code'):
                system_prompt += f"\n[EXECUTED CODE: {msg['code']}]"
        
        return system_prompt
    
    async def _process_autonomous_turn(self, response: str, df: pd.DataFrame, history: List[Dict]) -> Dict:
        """Process a single turn of autonomous execution with retry logic"""
        if self._contains_code_execution(response):
            code = self._extract_code_from_response(response)
            print("------------- CODE EXECUTED -------------")
            print(code)
            execution_result = self._execute_code(code, df)
            user_message = self._extract_user_message_from_response(response)
            
            retry_count = 0
            max_retries = 3  # Reduced for autonomous mode
            current_result = execution_result
            current_response = response
            current_code = code
            current_user_message = user_message
            
            # Retry logic for failed executions using same history
            while not current_result.get('success', False) and retry_count < max_retries:
                retry_count += 1
                print(f"------------- RETRY ATTEMPT {retry_count}/{max_retries} -------------")
                
                try:
                    error_msg = current_result['error']
                    print(f"EXECUTION ERROR: {error_msg}")
                except KeyError as e:
                    error_msg = f"Error: execution_result missing 'error' key. Keys: {list(current_result.keys())} - {str(e)}"
                    print(f"EXECUTION ERROR: {error_msg}")
                
                # Add failed attempt to history
                history.append({
                    'role': 'assistant',
                    'content': current_response,
                    'code': current_code,
                    'timestamp': datetime.now().isoformat()
                })
                
                error_feedback = f"I ran into an error executing your code. Here's the error:\n\n{error_msg}\n\nPlease fix the code and try again. Make sure to check the data types and column names."
                history.append({
                    'role': 'user', 
                    'content': error_feedback,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Build task-aware retry context for autonomous execution
                retry_context = self._build_task_aware_retry_context(history, df, current_response)
                retry_response = await self._get_model_response(retry_context, error_feedback)
                print("------------- RETRY RESPONSE -------------")
                print(retry_response)
                
                if self._contains_code_execution(retry_response):
                    retry_code = self._extract_code_from_response(retry_response)
                    print("------------- RETRY CODE EXECUTED -------------")
                    print(retry_code)
                    retry_execution_result = self._execute_code(retry_code, df)
                    retry_user_message = self._extract_user_message_from_response(retry_response)
                    
                    current_result = retry_execution_result
                    current_response = retry_response
                    current_code = retry_code
                    current_user_message = retry_user_message
                else:
                    return {
                        'message': retry_response,
                        'has_code': False,
                        'raw_response': retry_response,
                        'retry_attempt': True,
                        'retry_count': retry_count
                    }
            
            if not current_result.get('success', False):
                try:
                    final_error_msg = current_result['error']
                    print(f"FINAL ERROR AFTER {retry_count} RETRIES: {final_error_msg}")
                except KeyError as e:
                    final_error_msg = f"Error: final result missing 'error' key. Keys: {list(current_result.keys())} - {str(e)}"
                    print(f"FINAL ERROR AFTER {retry_count} RETRIES: {final_error_msg}")
            
            return {
                'message': current_user_message,
                'has_code': True,
                'execution_result': current_result,
                'raw_response': current_response,
                'executed_code': current_code,
                'retry_attempt': retry_count > 0,
                'retry_count': retry_count
            }
        else:
            return {
                'message': response,
                'has_code': False,
                'raw_response': response,
            }
    
    def _extract_continue_action(self, response: str) -> Optional[str]:
        """Extract the continue action from <continue_with> tags"""
        try:
            start = response.find("<continue_with>")
            if start == -1:
                return None
                
            start += len("<continue_with>")
            end = response.find("</continue_with>", start)
            if end == -1:
                return None
                
            return response[start:end].strip()
        except Exception as e:
            print(f"Error extracting continue action: {str(e)}")
            return None
    
    def _aggregate_autonomous_results(self, execution_turns: List[Dict], final_df: pd.DataFrame, turn_count: int) -> Dict:
        """Aggregate results from all autonomous execution turns"""
        # Get the final turn's message as the main response
        final_message = execution_turns[-1]['message'] if execution_turns else "Execution completed"
        
        # Check if any turn had code execution
        has_any_code = any(turn.get('has_code', False) for turn in execution_turns)
        
        # Get all executed code blocks
        all_code = []
        for turn in execution_turns:
            if turn.get('executed_code'):
                all_code.append(turn['executed_code'])
        
        # Final execution result
        final_execution_result = None
        if execution_turns:
            last_turn = execution_turns[-1]
            if last_turn.get('execution_result'):
                final_execution_result = last_turn['execution_result']
                # Update with final dataframe
                final_execution_result['dataframe'] = final_df
        
        return {
            'message': final_message,
            'has_code': has_any_code,
            'execution_result': final_execution_result,
            'raw_response': execution_turns[-1]['raw_response'] if execution_turns else "",
            'executed_code': '\n\n'.join(all_code) if all_code else None,
            'autonomous_execution': True,
            'turn_count': turn_count,
            'all_turns': execution_turns
        }