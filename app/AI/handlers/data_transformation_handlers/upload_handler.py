import io
import pandas as pd
from fastapi import UploadFile, File, HTTPException
from services.data_transformation_services.dataframe_state_service import DataFrameStateService

class UploadHandler:
    def __init__(self, df_state: DataFrameStateService):
        self.df_state = df_state
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    async def handle_upload(self, file: UploadFile = File(...)):
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file selected")
        
        if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
            raise HTTPException(status_code=400, detail="Only Excel and CSV files are supported")
        
        try:
            contents = await file.read()
            
            if file.filename.endswith('.csv'):
                uploaded_df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
            else:
                uploaded_df = pd.read_excel(io.BytesIO(contents))
            
            self.df_state.set_dataframe(uploaded_df)
            self.df_state.get_dataframe().to_csv('storage/data.csv', index=False)
            
            return {
                "message": "File uploaded successfully",
                "filename": file.filename,
                "shape": self.df_state.get_dataframe().shape,
                "columns": list(self.df_state.get_dataframe().columns),
                "preview": self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                "total_rows": len(self.df_state.get_dataframe()),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")