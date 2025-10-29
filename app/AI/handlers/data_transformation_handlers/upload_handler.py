import io
import pandas as pd
from flask import request, jsonify
from services.data_transformation_services.dataframe_state_service import DataFrameStateService

class UploadHandler:
    def __init__(self, df_state: DataFrameStateService):
        self.df_state = df_state
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    def handle_upload(self):
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
            return jsonify({"error": "Only Excel and CSV files are supported"}), 400
        
        try:
            contents = file.read()
            
            if file.filename.endswith('.csv'):
                uploaded_df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
            else:
                uploaded_df = pd.read_excel(io.BytesIO(contents))
            
            self.df_state.set_dataframe(uploaded_df)
            self.df_state.get_dataframe().to_csv('storage/data.csv', index=False)
            
            return jsonify({
                "message": "File uploaded successfully",
                "filename": file.filename,
                "shape": self.df_state.get_dataframe().shape,
                "columns": list(self.df_state.get_dataframe().columns),
                "preview": self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                "total_rows": len(self.df_state.get_dataframe()),
            })
        except Exception as e:
            return jsonify({"error": f"Error processing file: {str(e)}"}), 400