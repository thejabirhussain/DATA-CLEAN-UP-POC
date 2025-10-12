import re
import io
import time
import traceback
import numpy as np
import pandas as pd
from typing import Tuple, Any, Dict, List
from contextlib import redirect_stdout, redirect_stderr

class CodeExecutor:
    def __init__(self):
        self.security_validator = EnhancedSecurityValidator()
        
    
    def execute_code(self, code: str, df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        start_time = time.time()
        
        try:
            is_safe, safety_message = self.security_validator.validate_code(code)
            if not is_safe:
                error_log = f"Security validation failed: {safety_message}"
                return df, error_log
            
            result_df, execution_log = self._execute_code(code, df)
            
            execution_time = time.time() - start_time
            execution_log += f"\nExecution time: {execution_time:.3f}s"
            
            return result_df, execution_log
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_log = f"Execution failed after {execution_time:.3f}s\n"
            error_log += f"Error: {str(e)}\n"
            error_log += f"Traceback:\n{traceback.format_exc()}"
            return df, error_log
    
    
    def _execute_code(self, code: str, df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        # Allow full Python execution with common imports and df in locals
        execution_globals = {
            '__builtins__': __builtins__,
            'pandas': pd,
            'pd': pd,
            'numpy': np,
            'np': np,
            're': re,
            'datetime': __import__('datetime')
        }
        execution_locals = {'df': df.copy()}
        
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, execution_globals, execution_locals)
        
        result = execution_locals.get('df', df)
        
        stdout_content = stdout_capture.getvalue()
        stderr_content = stderr_capture.getvalue()
        
        execution_log = ""
        if stdout_content:
            execution_log += f"Output:\n{stdout_content}\n"
        if stderr_content:
            execution_log += f"Warnings:\n{stderr_content}\n"
        
        if not execution_log:
            execution_log = "Code executed successfully with no output."
        
        return result, execution_log
    

    
class EnhancedSecurityValidator:
    
    DANGEROUS_PATTERNS = [
        # Only block OS-related operations that could harm the computer
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
    
    def validate_code(self, code: str) -> Tuple[bool, str]:
        for pattern, message in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                return False, f"Dangerous operation detected: {message}"
        
        return True, "Code validation passed"
    
    
    