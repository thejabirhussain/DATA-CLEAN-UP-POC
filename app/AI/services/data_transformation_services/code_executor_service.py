import re
import io
import time
import traceback
import numpy as np
import pandas as pd
from typing import Tuple, Any, Dict, List, Optional
from contextlib import redirect_stdout, redirect_stderr

class CodeExecutorService:
    def __init__(self):
        self.security_validator = SecurityValidator()
    
    def execute_code(
        self, code: str, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Optional[str], Optional[str]]:
        # Security validation
        if not self.security_validator.validate_code(code):
            return df, None, "Security validation failed: Dangerous operation detected"

        execution_globals = {
            "__builtins__": __builtins__,
            "pandas": pd,
            "pd": pd,
            "numpy": np,
            "np": np,
            "re": re,
            "datetime": __import__("datetime"),
        }
        execution_locals = {"df": df.copy()}

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, execution_globals, execution_locals)

            result_df = execution_locals.get("df", df)

            # Get stdout content
            stdout_content = stdout_capture.getvalue()
            if stdout_content:
                print(stdout_content)  # Print to console for visibility

            output_msg = stdout_content if stdout_content else None
            return result_df, output_msg, None  # Success

        except Exception as e:
            error_msg = f"Error: {str(e)}\nTraceback:\n{traceback.format_exc()}"
            return df, None, error_msg  
    

    
class SecurityValidator:
    
    DANGEROUS_PATTERNS = [
        (r'import\s+os', "OS module import"),
        (r'from\s+os', "OS module import"),
        (r'import\s+subprocess', "Subprocess module import"),
        (r'from\s+subprocess', "Subprocess module import"),
        (r'import\s+shutil', "Shutil module import"),
        (r'from\s+shutil', "Shutil module import"),
        
        (r'\.system\s*\(', "System call"),
        (r'\.popen\s*\(', "Popen call"),
        (r'\.call\s*\(', "Call function"),
        (r'\.run\s*\(', "Run function"),
    ]
    
    def validate_code(self, code: str) -> bool:
        
        for pattern, message in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                return False
        
        return True