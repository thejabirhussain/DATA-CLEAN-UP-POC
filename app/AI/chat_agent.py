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
        return await self._get_ollama_response(full_prompt)
    
    async def _get_ollama_response(self, full_prompt: str) -> str:
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
            
            if response.status_code != 200:
                return f"Sorry, I'm having trouble connecting to Ollama. Error: {response.status_code} - {response.text}"
            
            try:
                result = response.json()
                raw_text = result.get("response", "I couldn't generate a response.")
                return raw_text
            except ValueError as json_error:
                return f"Sorry, I received an invalid response from Ollama. Raw response: {response.text[:200]}..."
            
        except requests.exceptions.RequestException as req_error:
            return f"Sorry, I couldn't connect to Ollama: {str(req_error)}"
        except Exception as e:
            return f"Sorry, I encountered an unexpected error with Ollama: {str(e)}"
    
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
            execution_result = self._execute_code_safely(code, df)
            user_message = self._extract_user_message_from_response(response)
            
            # If code execution failed, retry with error feedback
            if not execution_result.get('success', False):
                error_msg = execution_result.get('error', 'Unknown error')
                print(f"EXECUTION ERROR: {error_msg}")
                
                # Build error context and retry
                error_context = f"{context}\n\nUSER: {message}\nASSISTANT: {response}\n\nCODE EXECUTION ERROR: {error_msg}\n\nPlease fix the code and try again. The error above shows what went wrong."
                
                retry_response = await self._get_ollama_response(error_context + "\nASSISTANT:")
                print("------------- RETRY RESPONSE -------------")
                print(retry_response)
                
                if self._contains_code_execution(retry_response):
                    retry_code = self._extract_code_from_response(retry_response)
                    print("------------- RETRY CODE EXECUTED -------------")
                    print(retry_code)
                    retry_execution_result = self._execute_code_safely(retry_code, df)
                    retry_user_message = self._extract_user_message_from_response(retry_response)
                    
                    if not retry_execution_result.get('success', False):
                        retry_error_msg = retry_execution_result.get('error', 'Unknown error')
                        print(f"RETRY EXECUTION ERROR: {retry_error_msg}")
                    
                    return {
                        'message': retry_user_message,
                        'has_code': True,
                        'execution_result': retry_execution_result,
                        'raw_response': retry_response,
                        'executed_code': retry_code,
                        'retry_attempt': True
                    }
                else:
                    return {
                        'message': retry_response,
                        'has_code': False,
                        'raw_response': retry_response,
                        'retry_attempt': True
                    }
            
            return {
                'message': user_message,
                'has_code': True,
                'execution_result': execution_result,
                'raw_response': response,
                'executed_code': code
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
            # Extract all code blocks and combine them
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
            
            # Combine all code blocks with newlines
            return "\n".join(code_blocks) if code_blocks else ""
        except:
            return ""
    
    def _extract_user_message_from_response(self, response: str) -> str:
        try:
            code_start = response.find("<execute_code>")
            if code_start != -1:
                return response[:code_start].strip()
            
            return response
        except:
            return response

    def _execute_code_safely(self, code: str, df: pd.DataFrame) -> Dict:
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
                'error': str(e),
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