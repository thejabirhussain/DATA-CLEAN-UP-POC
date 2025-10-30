import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel
from services.data_transformation_services.transform_service import TransformService
from services.data_transformation_services.code_executor_service import CodeExecutorService
from services.data_transformation_services.dataframe_state_service import DataFrameStateService

class TransformRequest(BaseModel):
    instruction: str

class TransformHandler:
    def __init__(self, df_state: DataFrameStateService, coder_agent: TransformService, code_executor: CodeExecutorService):
        self.df_state = df_state
        self.coder_agent = coder_agent
        self.code_executor = code_executor
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    def handle_transform(self, request: TransformRequest):
        try:
            generated_code = self.coder_agent.process_instruction(
                request.instruction, 
                self.df_state.get_dataframe(),
                "ollama"
            )
            
            result_df, execution_log, error_msg = self.code_executor.execute_code(
                generated_code, 
                self.df_state.get_dataframe()
            )
            
            if error_msg:
                return {
                    "success": False,
                    "error": error_msg,
                    "generated_code": generated_code
                }
            
            self.df_state.update_dataframe(result_df)
            self.df_state.get_dataframe().to_csv('storage/data.csv', index=False)
            
            return {
                "success": True,
                "type": "transformation",
                "generated_code": generated_code,
                "execution_log": execution_log,
                "result_shape": self.df_state.get_dataframe().shape,
                "result_columns": list(self.df_state.get_dataframe().columns),
                "preview": self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                "total_rows": len(self.df_state.get_dataframe()),
            }
        except Exception as e:
            return {
                "error": str(e),
                "generated_code": generated_code if 'generated_code' in locals() else None
            }