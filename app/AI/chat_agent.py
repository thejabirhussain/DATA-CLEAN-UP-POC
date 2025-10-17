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
    def __init__(self):
        self.ollama_url = "http://localhost:11434/api/generate"
        self.ollama_model = "qwen3-coder:30b"
        self.code_executor = CodeExecutor()
        
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
            raw_text = result.get("response", "")
            return raw_text
            
        except Exception as e:
            error_msg = str(e)
            return f"Error in '_get_model_response': {(error_msg)}"
    
    async def _get_error_feedback_response(self, error_context_prompt: str) -> str:
        try:
            response = requests.post(self.ollama_url, json={
                "model": self.ollama_model,
                "prompt": error_context_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 600
                }
            })

            result = response.json()
            return result.get("response")
        
        except Exception as e:
            error_msg = str(e)
            return f"Error in '_get_error_feedback_response': {(error_msg)}"
    
    async def chat(self, message: str, conversation_history: List[Dict], df: pd.DataFrame = None, model_type: str = "ollama") -> Dict:
        print(f"USER: {message}")
        
        context = self._build_conversation_context(conversation_history, df)
        
        response = await self._get_model_response(context, message, model_type)
        print("------------- RAW MODEL RESPONSE -------------")
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
            
            # Create a temporary conversation history for retries
            retry_history = conversation_history.copy()
            
            while not current_result.get('success', False) and retry_count < max_retries:
                retry_count += 1
                print(f"------------- RETRY ATTEMPT {retry_count}/{max_retries} -------------")
                
                try:
                    error_msg = current_result['error']
                    print(f"EXECUTION ERROR: {error_msg}")
                except KeyError as e:
                    error_msg = f"Error in 'chat()': execution_result missing 'error' key. Keys: {list(current_result.keys())} - {str(e)}"
                    print(f"EXECUTION ERROR: {error_msg}")
                
                # Add the assistant's failed response to history
                retry_history.append({
                    'role': 'assistant',
                    'content': current_response,
                    'code': current_code,
                    'timestamp': datetime.now().isoformat()
                })
                
                error_feedback = f"I ran into an error executing your code. Here's the error:\n\n{error_msg}\n\nPlease fix the code and try again. Make sure to check the data types and column names."
                retry_history.append({
                    'role': 'user', 
                    'content': error_feedback,
                    'timestamp': datetime.now().isoformat()
                })
                
                retry_context = self._build_conversation_context(retry_history, df)
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
            error_msg = str(e)
            return f"Error in '_extract_code_from_response': {(error_msg)}"
    
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