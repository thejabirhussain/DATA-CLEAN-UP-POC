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
        self.ollama_model = "deepseek-r1:32b"
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
                    "num_predict": 1000
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
        context = self._build_conversation_context(conversation_history, df)
        
        response = await self._get_model_response(context, message, model_type)
        response = self._strip_deepseek_think(response)
        print("------------- RAW MODEL RESPONSE -------------")
        print(response)
        
        if self._contains_code_execution(response):
            code = self._extract_code_from_response(response)
            print("------------- CODE EXECUTED -------------")
            print(code)
            execution_result = self._execute_code_safely(code, df)
            user_message = self._extract_user_message_from_response(response)
            
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
            
    def _strip_deepseek_think(self, text: str) -> str:
        try:
            if not text:
                return text
            return re.sub(r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>", "", text, flags=re.IGNORECASE)
        except Exception:
            return text
    
    def _build_conversation_context(self, history: List[Dict], df: pd.DataFrame) -> str:
        df_info = self._get_dataframe_info(df) if df is not None else "No data loaded"
        
        system_prompt = f"""You are a conversational data analyst assistant helping a business user with their data.

CURRENT DATAFRAME INFO:
{df_info}

CONVERSATION RULES:
1. Be conversational and helpful - you can chat about data, answer questions, and perform transformations
2. When the user gives you MULTIPLE tasks or steps in one message, ask for clarification before executing
3. Break down multi-step requests and ask if they want all steps done at once or one by one
4. For single, clear data transformations, provide a brief business explanation then execute code
5. For data transformations, wrap your code in <execute_code> tags

CODE GENERATION RULES:
1. Generate ONLY executable Python code
2. The DataFrame is available as 'df'
3. Modify 'df' in-place or reassign it
4. These modules are already imported and available: pandas (as pd), numpy (as np), re, datetime, json, math
5. DO NOT include any import statements - all modules are pre-loaded
6. No file I/O operations
7. Do not use .head(), .describe(), .info(), print() - just modify the data

EXAMPLES:

User: "Concatenate first name and last name columns"
Response: "I'll combine the first and last name columns into a single full name column for you."
<execute_code>
df['Full Name'] = df['First Name'].astype(str) + ' ' + df['Last Name'].astype(str)
</execute_code>

User: "1) Create a full name column 2) Move it to the front 3) Delete the old columns"
Response: "I'll create the full name column, move it to the front, and remove the old columns all in one go."
<execute_code>
df['Full Name'] = df['First Name'].astype(str) + ' ' + df['Last Name'].astype(str)
cols = ['Full Name'] + [col for col in df.columns if col not in ['Full Name', 'First Name', 'Last Name']]
df = df[cols]
</execute_code>

User: "Clean the email column"
Response: "I'd be happy to clean the email column for you. Could you clarify what type of cleaning you need? For example:
- Remove extra spaces and trim whitespace?
- Convert to lowercase for consistency?
- Remove invalid email formats?
- Something else specific?"

User: "Remove extra spaces and convert to lowercase"
Response: "I'll clean the email column by removing extra spaces and converting everything to lowercase."
<execute_code>
df['Email'] = df['Email'].astype(str).str.strip().str.lower()
</execute_code>

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
            if "<execute_code>" in response:
                start = response.find("<execute_code>") + len("<execute_code>")
                end = response.find("</execute_code>")
                return response[start:end].strip()
            return ""
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
                print("Code execution error")
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
            print("Code execution error")
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