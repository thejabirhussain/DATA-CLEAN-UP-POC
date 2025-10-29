import requests
import pandas as pd
from typing import Dict, Any

class CoderAgent:
    def __init__(self):
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = "llama3.1:8b"
    
    def process_instruction(self, instruction: str, df: pd.DataFrame, model_type: str = "ollama") -> str:
        return self.generate_code(instruction, df, model_type)
    
    def generate_code(self, instruction: str, df: pd.DataFrame, model_type: str = "ollama") -> str:
        print(f"USER: {instruction}")
        df_info = self._get_dataframe_info(df)
        
        system_prompt = f"""You are a Python code generator for pandas DataFrame operations.

DATAFRAME INFO:
- Shape: {df_info['shape']}
- Columns: {df_info['columns']}
- Data types: {df_info['dtypes']}
- Sample data (first 3 rows):
{df_info['sample_data']}

RULES:
1. Generate ONLY executable Python code wrapped in ```python code blocks
2. The DataFrame is available as variable 'df' - this contains the user's data
3. Modify 'df' in-place or reassign it
4. Common modules are pre-imported: pandas (as pd), numpy (as np), re, datetime
5. You can import additional modules if needed (except os, subprocess, shutil for security)
6. No file I/O operations
8. Always ensure the code is safe and doesn't use dangerous operations

EXAMPLES:

User: "Concatenate first name and last name columns"
Response:
```python
df['Full Name'] = df['First Name'].astype(str) + ' ' + df['Last Name'].astype(str)
```

User: "Remove rows where email is invalid"
Response:
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
            
            result = response.json()
            generated_code = result.get("response", "")
            print("------------- LLM RESPONSE -------------")
            print(generated_code)
            
            code_blocks = []
            start_pos = 0
            
            while True:
                start = generated_code.find("```python", start_pos)
                if start == -1:
                    break
                    
                start += len("```python")
                end = generated_code.find("```", start)
                if end == -1:
                    break
                    
                code_block = generated_code[start:end].strip()
                if code_block:
                    code_blocks.append(code_block)
                
                start_pos = end + len("```")
            
            if code_blocks:
                generated_code = "\n".join(code_blocks)
            
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
    
