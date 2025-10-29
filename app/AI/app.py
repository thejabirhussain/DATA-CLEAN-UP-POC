import io
import os
import pandas as pd
import pytesseract
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from transform import CoderAgent
from code_executor import CodeExecutor
import chat_agent
from rag import RagSystem
from dataframe_state import DataFrameState

from typing import Optional
from datetime import datetime
from werkzeug.utils import secure_filename

pytesseract.pytesseract.tesseract_cmd = r"C:\dev\tesseract\tesseract.exe"

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure upload settings for RAG
PDF_UPLOAD_FOLDER = 'uploads/pdfs'
os.makedirs(PDF_UPLOAD_FOLDER, exist_ok=True)

# Dataframe state management
df_state = DataFrameState()

# Maintain full history stacks for robust undo/redo
undo_stack: list[pd.DataFrame] = []
redo_stack: list[pd.DataFrame] = []

coder_agent = CoderAgent()
code_executor = CodeExecutor()
conversation_history = []

# RAG system for document Q&A
rag_system: Optional[RagSystem] = None

def safe_to_dict(df: pd.DataFrame, orient='records'):
    df_clean = df.copy()
    df_clean = df_clean.where(pd.notnull(df_clean), None)
    return df_clean.to_dict(orient)

# Remove Pydantic models - Flask uses request.json directly

@app.route("/upload", methods=["POST"])
def upload_file():
    global undo_stack, redo_stack
    
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
        
        # Set dataframe in state
        df_state.set_dataframe(uploaded_df)
        
        # reset history stacks on new upload
        undo_stack = []
        redo_stack = []
        
        # Save uploaded data to data.csv immediately
        df_state.get_dataframe().to_csv('data.csv', index=False)
        
        return jsonify({
            "message": "File uploaded successfully",
            "filename": file.filename,
            "shape": df_state.get_dataframe().shape,
            "columns": list(df_state.get_dataframe().columns),
            "preview": safe_to_dict(df_state.get_dataframe().head(100)),
            "total_rows": len(df_state.get_dataframe()),
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        })
    except Exception as e:
        return jsonify({"error": f"Error processing file: {str(e)}"}), 400

@app.route("/transform", methods=["POST"])
def transform_data():
    global undo_stack, redo_stack
    
    data = request.get_json()
    if not data or 'instruction' not in data:
        return jsonify({"error": "No instruction provided"}), 400
    
    try:
        generated_code = coder_agent.process_instruction(
            data['instruction'], 
            df_state.get_dataframe(),
            "ollama"
        )

        # push current state to undo stack before applying transformation
        if df_state.has_dataframe():
            undo_stack.append(df_state.get_dataframe().copy())
            # optional cap to prevent excessive memory
            if len(undo_stack) > 50:
                undo_stack.pop(0)
        # clear redo history when a new transform occurs
        redo_stack = []
        
        result_df, execution_log, error_msg = code_executor.execute_code(generated_code, df_state.get_dataframe())
        
        # Check if there was an error
        if error_msg:
            return jsonify({
                "success": False,
                "error": error_msg,
                "generated_code": generated_code
            })
        
        df_state.update_dataframe(result_df)
        df_state.get_dataframe().to_csv('data.csv', index=False)
        
        return jsonify({
            "success": True,
            "type": "transformation",
            "generated_code": generated_code,
            "execution_log": execution_log,
            "result_shape": df_state.get_dataframe().shape,
            "result_columns": list(df_state.get_dataframe().columns),
            "preview": safe_to_dict(df_state.get_dataframe().head(100)),
            "total_rows": len(df_state.get_dataframe()),
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "generated_code": generated_code if 'generated_code' in locals() else None
        })

@app.route("/undo", methods=["POST"])
def undo_last_transformation():
    global undo_stack, redo_stack
    if not undo_stack:
        return jsonify({
            "success": False,
            "error": "Nothing to undo",
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        })

    print("Undo requested - restoring previous dataframe from stack")
    # move current to redo, pop last undo into current
    if df_state.has_dataframe():
        redo_stack.append(df_state.get_dataframe())
    df_state.update_dataframe(undo_stack.pop())

    df_state.get_dataframe().to_csv('data.csv', index=False)

    return jsonify({
        "success": True,
        "type": "transformation",
        "message": "Successfully undone last transformation",
        "result_shape": df_state.get_dataframe().shape,
        "result_columns": list(df_state.get_dataframe().columns),
        "preview": safe_to_dict(df_state.get_dataframe().head(100)),
        "total_rows": len(df_state.get_dataframe()),
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    })

@app.route("/redo", methods=["POST"])
def redo_last_undo():
    global undo_stack, redo_stack
    if not redo_stack:
        return jsonify({
            "success": False,
            "error": "Nothing to redo",
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        })

    print("Redo requested - re-applying last undone dataframe from stack")
    # move current to undo, pop last redo into current
    if df_state.has_dataframe():
        undo_stack.append(df_state.get_dataframe())
        if len(undo_stack) > 50:
            undo_stack.pop(0)
    df_state.update_dataframe(redo_stack.pop())

    df_state.get_dataframe().to_csv('data.csv', index=False)

    return jsonify({
        "success": True,
        "type": "transformation",
        "message": "Successfully redone last undo",
        "result_shape": df_state.get_dataframe().shape,
        "result_columns": list(df_state.get_dataframe().columns),
        "preview": safe_to_dict(df_state.get_dataframe().head(100)),
        "total_rows": len(df_state.get_dataframe()),
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    })


@app.route("/chat", methods=["POST"])
def chat_with_agent():
    global conversation_history, undo_stack, redo_stack
    
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "No message provided"}), 400
    
    try:
        # record user message
        conversation_history.append({
            'role': 'user',
            'content': data['message'],
            'timestamp': datetime.now().isoformat()
        })

        # Capture dataframe state before chat in case chat_agent modifies it internally
        pre_df = df_state.get_dataframe().copy() if df_state.has_dataframe() else None

        response = chat_agent.chat(
            data['message'],
            conversation_history,
            df_state
        )

        conversation_history.append({
            'role': 'assistant',
            'content': response['message'],
            'code': response.get('code'),
            'timestamp': datetime.now().isoformat()
        })

        dataframe_updated = False
        # Case 1: explicit execution_result in response
        if response.get('has_code') and response.get('execution_result'):
            execution_result = response['execution_result']
            if execution_result.get('success'):
                # push current to undo stack and clear redo
                if df_state.has_dataframe():
                    undo_stack.append(df_state.get_dataframe().copy())
                    if len(undo_stack) > 50:
                        undo_stack.pop(0)
                redo_stack = []

                df_state.update_dataframe(execution_result['dataframe'])
                df_state.get_dataframe().to_csv('data.csv', index=False)
                dataframe_updated = True
        else:
            # Case 2: chat_agent may have internally executed code and updated df_state
            if pre_df is not None and df_state.has_dataframe():
                try:
                    post_df = df_state.get_dataframe()
                    changed = not pre_df.equals(post_df)
                except Exception:
                    changed = True
                if changed:
                    # push pre-change to undo stack, clear redo
                    undo_stack.append(pre_df)
                    if len(undo_stack) > 50:
                        undo_stack.pop(0)
                    redo_stack = []
                    try:
                        df_state.get_dataframe().to_csv('data.csv', index=False)
                    except Exception:
                        pass
                    dataframe_updated = True

        # sanitize execution_result for response
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

        # Prepare response
        chat_response = {
            'success': True,
            'message': response['message'],
            'dataframe_updated': dataframe_updated,
            'raw_response': response.get('raw_response'),
            'executed_code': response.get('executed_code'),
            'execution_result': safe_execution_result,
            'undo_count': len(undo_stack),
            'redo_count': len(redo_stack),
        }
        
        # Add updated dataframe preview if dataframe was updated
        if dataframe_updated and df_state.has_dataframe():
            chat_response.update({
                'updated_preview': safe_to_dict(df_state.get_dataframe().head(100)),
                'updated_columns': list(df_state.get_dataframe().columns),
                'updated_shape': df_state.get_dataframe().shape,
                'updated_total_rows': len(df_state.get_dataframe()),
            })
        
        return jsonify(chat_response)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route("/data", methods=["GET"])
def get_data_page():
    global undo_stack, redo_stack
    
    page = int(request.args.get('page', 1))
    rows_per_page = int(request.args.get('rows_per_page', 10))
    
    if not df_state.has_dataframe():
        return jsonify({"error": "No data available"}), 400

    current_df = df_state.get_dataframe()
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
        "data": safe_to_dict(page_data),
        "columns": list(current_df.columns),
        "current_page": page,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "rows_per_page": rows_per_page,
        "start_row": start_idx + 1,
        "end_row": end_idx,
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    })

@app.route("/chat/history", methods=["GET"])
def get_chat_history():
    global conversation_history
    return jsonify({
        'messages': conversation_history[-20:],
        'total_messages': len(conversation_history)
    })

@app.route("/chat/clear", methods=["POST"])
def clear_chat_history():
    global conversation_history
    conversation_history = []
    return jsonify({'success': True, 'message': 'Chat history cleared'})

@app.route("/rag/upload", methods=["POST"])
def upload_pdf():
    global rag_system
    
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not file.filename.endswith('.pdf'):
        return jsonify({"error": "Only PDF files are supported"}), 400
    
    try:
        # Save the uploaded file
        filename = secure_filename(file.filename)
        filepath = os.path.join(PDF_UPLOAD_FOLDER, filename)
        
        file.save(filepath)
        
        # Initialize RAG system and index the PDF
        if rag_system is None:
            rag_system = RagSystem(model="llama3.1:8b")
        
        rag_system.index_pdf(filepath)
        
        return jsonify({
            "success": True,
            "message": "PDF uploaded and processed successfully",
            "filename": filename
        })
    except Exception as e:
        return jsonify({"error": f"Error processing PDF: {str(e)}"}), 500

@app.route("/rag/upload-multiple", methods=["POST"])
def upload_multiple_pdfs():
    global rag_system
    
    if 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400
    
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({"error": "No files selected"}), 400
    
    # Validate all files are PDFs
    for file in files:
        if not file.filename.endswith('.pdf'):
            return jsonify({"error": f"File {file.filename} is not a PDF. Only PDF files are supported"}), 400
    
    try:
        processed_files = []
        failed_files = []
        
        # Initialize RAG system if not exists
        if rag_system is None:
            rag_system = RagSystem(model="llama3.1:8b")
        
        # Process each file
        for file in files:
            try:
                filename = secure_filename(file.filename)
                filepath = os.path.join(PDF_UPLOAD_FOLDER, filename)
                
                file.save(filepath)
                
                # Index the PDF
                rag_system.index_pdf(filepath)
                processed_files.append(filename)
                
            except Exception as e:
                failed_files.append({
                    "filename": file.filename,
                    "error": str(e)
                })
        
        return jsonify({
            "success": len(failed_files) == 0,
            "message": f"Processed {len(processed_files)} PDF(s) successfully",
            "filenames": processed_files,
            "failed_files": failed_files
        })
    except Exception as e:
        return jsonify({"error": f"Error processing PDFs: {str(e)}"}), 500

@app.route("/rag/query", methods=["POST"])
def query_document():
    global rag_system
    
    data = request.get_json()
    if not data or 'question' not in data:
        return jsonify({"error": "No question provided"}), 400
    
    if rag_system is None:
        return jsonify({"error": "No PDF has been uploaded yet. Please upload a PDF first."}), 400
    
    try:
        response = rag_system.query(data['question'])
        return jsonify({
            "success": True,
            "answer": response
        })
    except Exception as e:
        return jsonify({"error": f"Error processing query: {str(e)}"}), 500

@app.route("/rag/status", methods=["GET"])
def get_rag_status():
    global rag_system
    
    return jsonify({
        "document_loaded": rag_system is not None and len(rag_system.pdf_names) > 0,
        "pdf_names": rag_system.pdf_names if rag_system else []
    })

@app.route("/rag/clear", methods=["POST"])
def clear_rag_system():
    global rag_system
    rag_system = None
    return jsonify({
        "success": True,
        "message": "RAG system cleared"
    })

@app.route("/")
def read_root():
    return send_from_directory("static", "index-react.html")

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory("static", filename)

if __name__ == "__main__":
    print("App Started")
    app.run(host="0.0.0.0", port=8000, debug=False)