import pandas as pd
from pydantic import BaseModel
from datetime import datetime
from services.data_transformation_services import chat_service
from services.data_transformation_services.dataframe_state_service import DataFrameStateService
from typing import List, Dict

class ChatRequest(BaseModel):
    message: str

class ChatHandler:
    def __init__(self, df_state: DataFrameStateService, conversation_history: List[Dict]):
        self.df_state = df_state
        self.gemini_chat = None
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    def handle_gemini_chat(self, request: ChatRequest):
        # Store DataFrame state before processing
        pre_df = self.df_state.get_dataframe().copy() if self.df_state.has_dataframe() else None

        # Use Gemini chat service
        from services.data_transformation_services.gemini_chat_service import GeminiChatService
        gemini_service = GeminiChatService()
        response = gemini_service.chat(request.message, self.df_state)
        
        # Check if DataFrame was updated
        dataframe_updated = False
        if pre_df is not None and self.df_state.has_dataframe():
            post_df = self.df_state.get_dataframe()
            dataframe_updated = not pre_df.equals(post_df)
        
        chat_response = {
            'success': True,
            'message': response['message'],
            'dataframe_updated': dataframe_updated,
            'raw_response': response.get('raw_response', response['message']),
        }
        
        if dataframe_updated and self.df_state.has_dataframe():
            chat_response.update({
                'updated_preview': self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                'updated_columns': list(self.df_state.get_dataframe().columns),
                'updated_shape': self.df_state.get_dataframe().shape,
                'updated_total_rows': len(self.df_state.get_dataframe()),
            })
        
        return chat_response

    def handle_ollama_chat(self, request: ChatRequest):
        # Store DataFrame state before processing
        pre_df = self.df_state.get_dataframe().copy() if self.df_state.has_dataframe() else None
        
        # Use Ollama chat service
        from services.data_transformation_services.chat_service import chat
        response = chat(request.message, [], self.df_state)
        
        # Check if DataFrame was updated
        dataframe_updated = False
        if pre_df is not None and self.df_state.has_dataframe():
            post_df = self.df_state.get_dataframe()
            dataframe_updated = not pre_df.equals(post_df)
        
        chat_response = {
            'success': True,
            'message': response['message'],
            'dataframe_updated': dataframe_updated,
            'raw_response': response.get('raw_response', response['message']),
        }
        
        if dataframe_updated and self.df_state.has_dataframe():
            chat_response.update({
                'updated_preview': self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                'updated_columns': list(self.df_state.get_dataframe().columns),
                'updated_shape': self.df_state.get_dataframe().shape,
                'updated_total_rows': len(self.df_state.get_dataframe()),
            })
        
        return chat_response
    
    def handle_chat(self, request: ChatRequest):
        model_type = "ollama"  # "gemini" or "ollama"
        
        if model_type.lower() == "gemini":
            return self.handle_gemini_chat(request)
        else:
            return self.handle_ollama_chat(request)