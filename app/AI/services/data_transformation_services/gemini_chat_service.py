import os
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional
from datetime import datetime

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../../.env'))
load_dotenv()

gemini_api_key = os.getenv('GEMINI_API_KEY')
if not gemini_api_key:
    raise ValueError("GEMINI_API_KEY environment variable is required")
genai.configure(api_key=gemini_api_key)

GEMINI_MODEL = "gemini-2.5-flash"

class GeminiChatService:
    def __init__(self, model_name: str = GEMINI_MODEL, df_state=None):
        self.model_name = model_name
        self.chat_session = None
        self.df_state = df_state
        self._initialize_session()
    
    def _initialize_session(self):
        system_instruction = self._build_system_instruction()
        
        model = genai.GenerativeModel(
            self.model_name,
            system_instruction=system_instruction,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=400,
            )
        )
        self.chat_session = model.start_chat(history=[])
    
    def _get_column_info_tool(self):
        if not self.df_state or not self.df_state.has_dataframe():
            return "No dataframe available"
        
        df = self.df_state.get_dataframe()
        info = []
        for col in df.columns:
            info.append(f"{col}: {df[col].dtype}")
        return "Columns and types:\n" + "\n".join(info)
    
    def _get_sample_data_tool(self, columns: list = None):
        if not self.df_state or not self.df_state.has_dataframe():
            return "No dataframe available"
        
        df = self.df_state.get_dataframe()
        if not columns:
            columns = df.columns.tolist()[:5]
            
        result = []
        for col in columns:
            if col in df.columns:
                sample_values = df[col].head(5).tolist()
                result.append(f"{col}: {sample_values}")
            else:
                result.append(f"{col}: Column not found")
        return "Sample data:\n" + "\n".join(result)
    
   
    
    def _execute_pandas_code_tool(self, code: str):
        if not self.df_state or not self.df_state.has_dataframe():
            return "No dataframe available"
        
        try:
            # Import the execute_code function
            from .chat_service import execute_code
            success, output = execute_code(code, self.df_state)
            
            if success:
                return f"Code executed successfully: {output}"
            else:
                return f"Code execution failed: {output}"
        except Exception as e:
            return f"Error executing code: {str(e)}"
    
    def _build_system_instruction(self):
        
        base_instruction = """You are a DataFrame transformation assistant.

AVAILABLE TOOLS:
1. get_column_info() - Returns column names with dtypes
2. get_sample_data(columns: list) - Returns sample values for specified columns

You must respond with valid JSON in this exact format:
{
  "tools": [list of tools to call] | null,
  "code": "python code to execute" | null,
  "tasks_completed": true/false,
  "message": "final response to user" | null
}

WORKFLOW:
1. Execute ONE transformation at a time on dataframe 'df' directly
2. ONLY use tools when you encounter errors to debug the issue
3. When ALL tasks are complete, set tasks_completed=true and provide final message
4. Do NOT use tools proactively - only for error debugging

ENVIRONMENT:
- Available modules: pandas (pd), numpy (np), datetime, re
- Work directly on dataframe 'df' - do NOT import modules or create new variables"""

        if self.df_state and self.df_state.has_dataframe():
            df_info = f"""

CURRENT DATAFRAME INFO:
Columns: {self.df_state.get_dataframe().columns.tolist()}
Shape: {self.df_state.get_dataframe().shape}
Data Types: {self.df_state.get_dataframe().dtypes.to_dict()}
Sample Data:
{self.df_state.get_dataframe().head().to_string()}"""
            return base_instruction + df_info
        
        return base_instruction
    
    def send_message(self, message: str) -> str:
        """Send a message to the Gemini chat session"""
        if not self.chat_session:
            self._initialize_session()
        
        response = self.chat_session.send_message(message)
        return response.text
   