import pandas as pd
from flask import request, jsonify
from services.data_transformation_services.dataframe_state_service import DataFrameStateService

class DataHandler:
    def __init__(self, df_state: DataFrameStateService):
        self.df_state = df_state
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    def handle_data_retrieval(self):
        page = int(request.args.get('page', 1))
        rows_per_page = int(request.args.get('rows_per_page', 10))
        
        if not self.df_state.has_dataframe():
            return jsonify({"error": "No data available"}), 400

        current_df = self.df_state.get_dataframe()
        total_rows = len(current_df)
        total_pages = (total_rows + rows_per_page - 1) // rows_per_page
        if total_pages == 0:
            total_pages = 1
        if page < 1 or page > total_pages:
            return jsonify({"error": f"Invalid page number. Must be between 1 and {total_pages}"}), 400

        start_idx = (page - 1) * rows_per_page
        end_idx = min(start_idx + rows_per_page, total_rows)
        page_data = current_df.iloc[start_idx:end_idx]

        return jsonify({
            "data": self.safe_to_dict(page_data),
            "columns": list(current_df.columns),
            "current_page": page,
            "total_pages": total_pages,
            "total_rows": total_rows,
            "rows_per_page": rows_per_page,
            "start_row": start_idx + 1,
            "end_row": end_idx,
        })