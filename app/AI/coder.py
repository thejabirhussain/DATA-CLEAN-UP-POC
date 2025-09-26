import requests
import pandas as pd
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

class CoderAgent:
    def __init__(self):
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = "qwen3-coder:30b"
    
    async def process_instruction(self, instruction: str, df: pd.DataFrame) -> str:
        return await self.generate_code(instruction, df)
    
    async def generate_code(self, instruction: str, df: pd.DataFrame) -> str:
        df_info = self._get_dataframe_info(df)
        
        system_prompt = f"""You are a Python code generator for pandas DataFrame operations.

DATAFRAME INFO:
- Shape: {df_info['shape']}
- Columns: {df_info['columns']}
- Data types: {df_info['dtypes']}
- Sample data (first 3 rows):
{df_info['sample_data']}

RULES:
1. Generate ONLY executable Python code
2. The DataFrame is available as 'df'
3. Modify 'df' in-place or reassign it
4. These modules are already imported and available: pandas (as pd), numpy (as np), re, datetime, json, math
5. DO NOT include any import statements - all modules are pre-loaded
6. No file I/O operations
7. Always ensure the code is safe and doesn't use dangerous operations

EXAMPLES:

User: "Concatenate first name and last name columns"
Code:
```python
df['Full Name'] = df['First Name'].astype(str) + ' ' + df['Last Name'].astype(str)
```

User: "Remove rows where email is invalid"
Code:
```python
email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{{2,}}'
valid_emails = df['Email'].astype(str).str.match(email_pattern, na=False)
df = df[valid_emails].reset_index(drop=True)
```

Generate code for: "{instruction}"
"""

        try:
            full_prompt = f"{system_prompt}\n\nUser instruction: {instruction}"
            response = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1000
                }
            })
            
            if response.status_code != 200:
                raise Exception(f"Ollama API error: {response.status_code} - {response.text}")
            
            result = response.json()
            generated_code = result.get("response", "")
            if "```python" in generated_code:
                code_start = generated_code.find("```python") + 9
                code_end = generated_code.find("```", code_start)
                generated_code = generated_code[code_start:code_end].strip()
            elif "```" in generated_code:
                code_start = generated_code.find("```") + 3
                code_end = generated_code.find("```", code_start)
                generated_code = generated_code[code_start:code_end].strip()
            
            return generated_code
            
        except Exception as e:
            raise Exception(f"Failed to generate code: {str(e)}")
    
    def _get_dataframe_info(self, df: pd.DataFrame) -> Dict[str, Any]:
        return {
            'shape': df.shape,
            'columns': list(df.columns),
            'dtypes': df.dtypes.astype(str).to_dict(),
            'sample_data': df.head(3).to_string()
        }
    
    async def explain_code(self, code: str) -> str:
        try:
            prompt = f"Explain what this pandas code does in simple terms:\n\n{code}"
            
            response = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 200
                }
            })
            
            if response.status_code != 200:
                return f"Could not explain code: API error {response.status_code}"
            
            result = response.json()
            return result.get("response", "No explanation available")
            
        except Exception as e:
            return f"Could not explain code: {str(e)}"