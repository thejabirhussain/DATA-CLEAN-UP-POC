import pandas as pd
from flask import request, jsonify
from datetime import datetime
from services.data_transformation_services import chat_service
from services.data_transformation_services.dataframe_state_service import DataFrameStateService
from typing import List, Dict

class ChatHandler:
    def __init__(self, df_state: DataFrameStateService, conversation_history: List[Dict]):
        self.df_state = df_state
        self.conversation_history = conversation_history
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    def handle_chat(self):
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "No message provided"}), 400
        
        try:
            self.conversation_history.append({
                'role': 'user',
                'content': data['message'],
                'timestamp': datetime.now().isoformat()
            })

            pre_df = self.df_state.get_dataframe().copy() if self.df_state.has_dataframe() else None

            response = chat_service.chat(
                data['message'],
                self.conversation_history,
                self.df_state
            )

            self.conversation_history.append({
                'role': 'assistant',
                'content': response['message'],
                'code': response.get('code'),
                'timestamp': datetime.now().isoformat()
            })

            dataframe_updated = False
            if response.get('has_code') and response.get('execution_result'):
                execution_result = response['execution_result']
                if execution_result.get('success'):
                    self.df_state.update_dataframe(execution_result['dataframe'])
                    self.df_state.get_dataframe().to_csv('storage/data.csv', index=False)
                    dataframe_updated = True
            else:
                if pre_df is not None and self.df_state.has_dataframe():
                    try:
                        post_df = self.df_state.get_dataframe()
                        changed = not pre_df.equals(post_df)
                    except Exception:
                        changed = True
                    if changed:
                        try:
                            self.df_state.get_dataframe().to_csv('storage/data.csv', index=False)
                        except Exception:
                            pass
                        dataframe_updated = True

            safe_execution_result = None
            if response.get('execution_result') is not None:
                er = dict(response['execution_result'])
                if 'dataframe' in er:
                    er.pop('dataframe', None)
                if isinstance(er.get('original_shape'), (list, tuple)):
                    er['original_shape'] = [int(x) for x in er['original_shape']]
                if isinstance(er.get('new_shape'), (list, tuple)):
                    er['new_shape'] = [int(x) for x in er['new_shape']]
                if 'execution_log' in er and er['execution_log'] is not None:
                    er['execution_log'] = str(er['execution_log'])
                if 'error' in er and er['error'] is not None:
                    er['error'] = str(er['error'])
                safe_execution_result = er

            chat_response = {
                'success': True,
                'message': response['message'],
                'dataframe_updated': dataframe_updated,
                'raw_response': response.get('raw_response'),
                'executed_code': response.get('executed_code'),
                'execution_result': safe_execution_result,
            }
            
            if dataframe_updated and self.df_state.has_dataframe():
                chat_response.update({
                    'updated_preview': self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                    'updated_columns': list(self.df_state.get_dataframe().columns),
                    'updated_shape': self.df_state.get_dataframe().shape,
                    'updated_total_rows': len(self.df_state.get_dataframe()),
                })
            
            return jsonify(chat_response)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            })