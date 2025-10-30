import os
from fastapi import UploadFile, HTTPException
from typing import Optional, List
from services.rag_services.rag_service import RagSystem
import re

class RagUploadHandler:
    def __init__(self, rag_system: Optional[RagSystem], upload_folder: str):
        self.rag_system = rag_system
        self.upload_folder = upload_folder
    
    def secure_filename(self, filename: str) -> str:
        """Secure a filename by removing unsafe characters"""
        filename = re.sub(r'[^\w\s.-]', '', filename)
        filename = re.sub(r'[-\s]+', '-', filename)
        return filename.strip('-')
    
    async def handle_upload(self, files: List[UploadFile]):
        try:
            print(f"RAG Upload: Received {len(files) if files else 0} files")
            
            if not files or all(not file.filename for file in files):
                raise HTTPException(status_code=400, detail="No files provided")
            
            # Filter out empty files
            valid_files = [f for f in files if f.filename and f.filename.strip()]
            print(f"RAG Upload: {len(valid_files)} valid files after filtering")
            
            if not valid_files:
                raise HTTPException(status_code=400, detail="No valid files provided")
            
            for file in valid_files:
                if not file.filename.endswith('.pdf'):
                    raise HTTPException(status_code=400, detail=f"File {file.filename} is not a PDF. Only PDF files are supported")
            
            processed_files = []
            failed_files = []
            
            try:
                if self.rag_system is None:
                    print("RAG Upload: Initializing RAG system...")
                    #self.rag_system = RagSystem(model="qwen3-coder:30b")
                    self.rag_system = RagSystem(model="llama3.1:8b")
                    print("RAG Upload: RAG system initialized successfully")
            except Exception as e:
                print(f"RAG Upload: Failed to initialize RAG system: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to initialize RAG system: {str(e)}")
            
            for file in valid_files:
                try:
                    print(f"RAG Upload: Processing file {file.filename}")
                    filename = self.secure_filename(file.filename)
                    filepath = os.path.join(self.upload_folder, filename)
                    
                    # Save file
                    contents = await file.read()
                    with open(filepath, 'wb') as f:
                        f.write(contents)
                    print(f"RAG Upload: File saved to {filepath}")
                    
                    print(f"RAG Upload: Starting PDF indexing for {filename}")
                    self.rag_system.index_pdf(filepath)
                    print(f"RAG Upload: PDF indexing completed for {filename}")
                    processed_files.append(filename)
                    
                except Exception as e:
                    print(f"RAG Upload: Error processing {file.filename}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    failed_files.append({
                        "filename": file.filename,
                        "error": str(e)
                    })
            
            file_count = len(processed_files)
            if file_count == 1:
                message = f"Successfully processed 1 PDF: {processed_files[0]}"
            else:
                message = f"Successfully processed {file_count} PDFs"
            
            result = {
                "success": len(failed_files) == 0,
                "message": message,
                "filenames": processed_files,
                "failed_files": failed_files,
                "total_processed": file_count
            }
            print(f"RAG Upload: Returning result: {result}")
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"RAG Upload Error: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
    def get_rag_system(self):
        return self.rag_system