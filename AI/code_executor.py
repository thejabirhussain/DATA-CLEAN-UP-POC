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
        self.allowed_modules = {
            'pandas': pd,
            'numpy': np,
            'np': np,
            'pd': pd,
            're': re,
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json')
        }
        
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
        safe_globals = self._create_safe_globals()
        safe_locals = {'df': df.copy()}
        
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, safe_globals, safe_locals)
        
        result = safe_locals.get('df', df)
        
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
    
    def _create_safe_globals(self) -> Dict[str, Any]:
        safe_globals = {
            '__builtins__': {
                'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
                'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
                'range': range, 'enumerate': enumerate, 'zip': zip,
                'map': map, 'filter': filter, 'sorted': sorted,
                'sum': sum, 'min': min, 'max': max, 'abs': abs, 'round': round,
                'print': print, 'type': type, 'isinstance': isinstance,
                'hasattr': hasattr, 'getattr': getattr, 'setattr': setattr,
                
                'any': any, 'all': all, 'chr': chr, 'ord': ord,
                'hex': hex, 'oct': oct, 'bin': bin, 'pow': pow,
                'divmod': divmod, 'reversed': reversed,
                
                'Exception': Exception, 'ValueError': ValueError,
                'TypeError': TypeError, 'KeyError': KeyError,
                'IndexError': IndexError, 'AttributeError': AttributeError
            }
        }
        
        safe_globals.update(self.allowed_modules)
        
        return safe_globals
    
class EnhancedSecurityValidator:
    
    DANGEROUS_PATTERNS = [

        (r'import\s+os', "OS module import"),
        (r'import\s+sys', "System module import"),
        (r'import\s+subprocess', "Subprocess module import"),
        (r'import\s+shutil', "Shutil module import"),
        (r'from\s+os', "OS module import"),
        (r'from\s+sys', "System module import"),
        (r'from\s+subprocess', "Subprocess module import"),
        
        (r'__import__', "Dynamic import"),
        (r'eval\s*\(', "Eval function"),
        (r'exec\s*\(', "Exec function"),
        (r'compile\s*\(', "Compile function"),
        
        (r'open\s*\(', "File open operation"),
        (r'file\s*\(', "File operation"),
        (r'\.read\s*\(', "File read operation"),
        (r'\.write\s*\(', "File write operation"),
        
        (r'input\s*\(', "Input function"),
        (r'raw_input\s*\(', "Raw input function"),
        
        (r'globals\s*\(', "Globals access"),
        (r'locals\s*\(', "Locals access"),
        (r'vars\s*\(', "Vars function"),
        (r'dir\s*\(', "Dir function"),
        
        (r'delattr', "Delattr function"),
        (r'setattr.*__', "Setattr with dunder attributes"),
        (r'getattr.*__', "Getattr with dunder attributes"),
        
        (r'\.system\s*\(', "System call"),
        (r'\.popen\s*\(', "Popen call"),
        (r'\.call\s*\(', "Call function"),
        (r'\.run\s*\(', "Run function"),
        
        (r'import\s+urllib', "URL library import"),
        (r'import\s+requests', "Requests library import"),
        (r'import\s+socket', "Socket library import"),
        (r'from\s+urllib', "URL library import"),
        (r'from\s+requests', "Requests library import"),
        
        (r'import\s+threading', "Threading import"),
        (r'import\s+multiprocessing', "Multiprocessing import"),
        (r'from\s+threading', "Threading import"),
        (r'from\s+multiprocessing', "Multiprocessing import"),
    ]
    
    def validate_code(self, code: str) -> Tuple[bool, str]:
        for pattern, message in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                return False, f"Dangerous operation detected: {message}"
        
        return True, "Code validation passed"
    
    
    