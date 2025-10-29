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

To use a tool, include it in the tools array:
{"tools": [{"tool": "get_column_info", "params": {}}]}

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
- Work directly on dataframe 'df' - do NOT import modules or create new variables

EXAMPLES:

User: "Remove the ID column"
{
  "tools": null,
  "code": "df = df.drop(columns=['ID'])",
  "tasks_completed": false,
  "message": null
}
[You get: "Code executed successfully"]
{
  "tools": null,
  "code": null,
  "tasks_completed": true,
  "message": "Done! Removed the ID column."
}

User: "Make name column lowercase" (encounters error)
{
  "tools": null,
  "code": "df['name'] = df['name'].str.lower()",
  "tasks_completed": false,
  "message": null
}
[You get error: AttributeError: 'float' object has no attribute 'str']
{
  "tools": [{"tool": "get_sample_data", "params": {"columns": ["name"]}}],
  "code": null,
  "tasks_completed": false,
  "message": null
}
[You get sample data showing it's float values]
{
  "tools": null,
  "code": "df['name'] = df['name'].astype(str).str.lower()",
  "tasks_completed": false,
  "message": null
}
[You get: "Code executed successfully"]
{
  "tools": null,
  "code": null,
  "tasks_completed": true,
  "message": "Done! Made name column lowercase."
}

CRITICAL: Use tools to understand data structure and debug errors. Execute one transformation at a time. message must be null until ALL tasks are complete!"""

        if self.df_state and self.df_state.has_dataframe():
            df_info = f"""

DATAFRAME INFO:
Columns: {self.df_state.get_dataframe().columns.tolist()}
Shape: {self.df_state.get_dataframe().shape}
Data Types: {self.df_state.get_dataframe().dtypes.to_dict()}
Sample Data:
{self.df_state.get_dataframe().head().to_string()}"""
            return base_instruction + df_info
        
        return base_instruction
    
    def send_message(self, message: str) -> str:
        if not self.chat_session:
            self._initialize_session()
        
        response = self.chat_session.send_message(message)
        return response.text

    def chat(self, message: str, df_state) -> Dict[str, Any]:
        """Main chat function with conversation loop - matches Ollama architecture"""
        if not df_state.has_dataframe():
            return {
                "message": "No dataframe available. Please upload a file first.",
                "has_code": False,
            }

        # Update df_state for this conversation
        self.df_state = df_state
        self._initialize_session()  # Reinitialize with new DataFrame info

        max_turns = 5
        turn_count = 0
        current_message = message
        
        # Initialize conversation log with system instruction
        system_instruction = self._build_system_instruction()
        gemini_conversation = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": message}
        ]

        while turn_count < max_turns:
            print(f"\n====================")

            # Send message to Gemini
            llm_response = self.send_message(current_message)
            turn_count += 1
            print(f"\n========== GEMINI TURN {turn_count} ==========")
            print(f"Response: {llm_response}")
            
            # Log the conversation
            gemini_conversation.append({"role": "assistant", "content": llm_response})

            # Parse JSON response
            json_response = self._extract_json_response(llm_response)
            if not json_response:
                # If no valid JSON, treat as final message
                final_message = llm_response
                break

            # Check if tasks are completed
            if json_response.get("tasks_completed", False):
                final_message = json_response.get("message", "Task completed")
                print(f"All tasks completed: {final_message}")
                break

            # Execute tools if requested
            if json_response.get("tools"):
                tool_results = self._execute_tools(json_response["tools"], df_state)
                print(f"Tool results: {tool_results}")
                current_message = f"Tool results:\n{tool_results}"
                gemini_conversation.append({"role": "user", "content": current_message})
                continue

            # Execute code if provided
            if json_response.get("code"):
                success, output = self._execute_code(json_response["code"], df_state)
                if success:
                    print(f"Code executed successfully: {output}")
                    current_message = f"Code executed successfully. Output:\n{output}"
                else:
                    print(f"Code execution failed: {output}")
                    current_message = f"Code failed with error:\n{output}\n\nFix it and try again."
                gemini_conversation.append({"role": "user", "content": current_message})
                continue

            # If no tools or code, ask for clarification
            current_message = "Please provide code or tools in the JSON response."
            gemini_conversation.append({"role": "user", "content": current_message})

        # Use final message or fallback
        if 'final_message' not in locals():
            final_message = "Task execution stopped - maximum turns reached."

        # Log the conversation
        self._log_conversation(gemini_conversation, message, final_message)

        return {
            "message": final_message,
            "has_code": True,
            "raw_response": final_message,
        }

    def _extract_json_response(self, response: str) -> Optional[Dict[str, Any]]:
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

    def _execute_tools(self, tools: list, df_state) -> str:
        results = []
        for tool_call in tools:
            tool_name = tool_call.get("tool")
            params = tool_call.get("params", {})
            
            if tool_name == "get_column_info":
                result = self._get_column_info_tool()
            elif tool_name == "get_sample_data":
                columns = params.get("columns", [])
                result = self._get_sample_data_tool(columns)
            else:
                result = f"Unknown tool: {tool_name}"
            
            results.append(result)
        
        return "\n\n".join(results)

    def _execute_code(self, code: str, df_state) -> tuple[bool, Optional[str]]:
        if not code:
            return False, "No code provided"

        if not df_state.has_dataframe():
            return False, "No dataframe available"

        # Import the execute_code function from chat_service
        from .chat_service import execute_code
        return execute_code(code, df_state)

    def _log_conversation(self, conversation, original_message, final_message):
        with open("storage/conversation_log.txt", "w", encoding="utf-8") as log_file:
            log_file.write(f"\n{'='*80}\n")
            log_file.write(f"GEMINI CONVERSATION LOG\n")
            log_file.write(f"{'='*80}\n\n")
            log_file.write(f"Original User Message: {original_message}\n\n")
            
            # Log each turn in the conversation
            for i, msg in enumerate(conversation, 1):
                role = msg["role"].upper()
                content = msg["content"]
                log_file.write(f"{role} (Turn {i}):\n{content}\n\n")
            
            log_file.write(f"{'='*80}\n")
            log_file.write(f"FINAL MESSAGE: {final_message}\n")
            log_file.write(f"{'='*80}\n")
            log_file.write(f"CONVERSATION COMPLETED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"{'='*80}\n")