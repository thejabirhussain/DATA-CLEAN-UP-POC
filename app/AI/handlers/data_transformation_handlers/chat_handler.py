import pandas as pd
from flask import request, jsonify
from datetime import datetime
from services.data_transformation_services import chat_service
from services.data_transformation_services.dataframe_state_service import DataFrameStateService
from typing import List, Dict

class ChatHandler:
    def __init__(self, df_state: DataFrameStateService, conversation_history: List[Dict]):
        self.df_state = df_state
        self.gemini_chat = None
    
    def safe_to_dict(self, df: pd.DataFrame, orient='records'):
        df_clean = df.copy()
        df_clean = df_clean.where(pd.notnull(df_clean), None)
        return df_clean.to_dict(orient)
    
    def _log_gemini_conversation(self, conversation, original_message, final_message):
        """Log the Gemini conversation to conversation_log.txt"""
        with open("storage/conversation_log.txt", "w", encoding="utf-8") as log_file:
            log_file.write(f"\n{'='*80}\n")
            log_file.write(f"GEMINI CONVERSATION LOG\n")
            log_file.write(f"{'='*80}\n\n")
            log_file.write(f"Original User Message: {original_message}\n\n")
            
            # Log each turn in the conversation
            for i, msg in enumerate(conversation, 1):
                role = msg["role"].upper()
                content = msg["content"]
                log_file.write(f"{role} (Turn {i}):\n{content}\n\n")
            
            log_file.write(f"{'='*80}\n")
            log_file.write(f"FINAL MESSAGE: {final_message}\n")
            log_file.write(f"{'='*80}\n")
            log_file.write(f"CONVERSATION COMPLETED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"{'='*80}\n")
    
    def handle_gemini_chat(self):
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "No message provided"}), 400
        
        if not self.gemini_chat:
            from services.data_transformation_services.gemini_chat_service import GeminiChatService
            self.gemini_chat = GeminiChatService(df_state=self.df_state)
        
        # Store DataFrame state before processing
        pre_df = self.df_state.get_dataframe().copy() if self.df_state.has_dataframe() else None
        
        # Conversation loop with Gemini
        from services.data_transformation_services.chat_service import extract_json_response, execute_tools, execute_code
        
        max_turns = 5
        turn_count = 0
        current_message = data['message']
        final_message = None
        
        # Initialize conversation log
        gemini_conversation = [
            {"role": "user", "content": data['message']}
        ]
        
        while turn_count < max_turns:
            # Send message to Gemini
            llm_response = self.gemini_chat.send_message(current_message)
            turn_count += 1
            print(f"\n========== GEMINI TURN {turn_count} ==========")
            print(f"Response: {llm_response}")
            
            # Log the conversation
            gemini_conversation.append({"role": "assistant", "content": llm_response})
            
            # Parse JSON response
            json_response = extract_json_response(llm_response)
            if not json_response:
                # If no valid JSON, treat as final message
                final_message = llm_response
                break
            
            # Check if tasks are completed
            if json_response.get("tasks_completed", False):
                final_message = json_response.get("message", "Task completed")
                print(f"All tasks completed: {final_message}")
                break
            
            # Execute tools if requested
            if json_response.get("tools"):
                tool_results = execute_tools(json_response["tools"], self.df_state)
                print(f"Tool results: {tool_results}")
                current_message = f"Tool results:\n{tool_results}"
                gemini_conversation.append({"role": "user", "content": current_message})
                continue
            
            # Execute code if provided
            if json_response.get("code"):
                success, output = execute_code(json_response["code"], self.df_state)
                if success:
                    print(f"Code executed successfully: {output}")
                    current_message = f"Code executed successfully. Output:\n{output}"
                else:
                    print(f"Code execution failed: {output}")
                    current_message = f"Code failed with error:\n{output}\n\nFix it and try again."
                gemini_conversation.append({"role": "user", "content": current_message})
                continue
            
            # If no tools or code, ask for clarification
            current_message = "Please provide code or tools in the JSON response."
            gemini_conversation.append({"role": "user", "content": current_message})
        
        # Use final message or fallback
        if not final_message:
            final_message = "Task execution stopped - maximum turns reached."
        
        # Log the final conversation
        self._log_gemini_conversation(gemini_conversation, data['message'], final_message)
        
        # Check if DataFrame was updated
        dataframe_updated = False
        if pre_df is not None and self.df_state.has_dataframe():
            post_df = self.df_state.get_dataframe()
            dataframe_updated = not pre_df.equals(post_df)
        
        chat_response = {
            'success': True,
            'message': final_message,
            'dataframe_updated': dataframe_updated,
            'raw_response': final_message,
        }
        
        if dataframe_updated and self.df_state.has_dataframe():
            chat_response.update({
                'updated_preview': self.safe_to_dict(self.df_state.get_dataframe().head(100)),
                'updated_columns': list(self.df_state.get_dataframe().columns),
                'updated_shape': self.df_state.get_dataframe().shape,
                'updated_total_rows': len(self.df_state.get_dataframe()),
            })
        
        return jsonify(chat_response)  

    def handle_ollama_chat(self):
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "No message provided"}), 400
        
        # Store DataFrame state before processing
        pre_df = self.df_state.get_dataframe().copy() if self.df_state.has_dataframe() else None
        
        # Use Ollama chat service
        from services.data_transformation_services.chat_service import chat
        response = chat(data['message'], [], self.df_state)
        
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
        
        return jsonify(chat_response)
    
    def handle_chat(self):
        model_type = "gemini"  # "gemini" or "ollama"
        
        if model_type.lower() == "gemini":
            return self.handle_gemini_chat()
        else:
            return self.handle_ollama_chat()