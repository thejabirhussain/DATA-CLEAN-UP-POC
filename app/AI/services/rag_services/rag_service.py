import os
import re
import json
import uuid
import shutil
import textwrap
import pytesseract
from PIL import Image
from typing import List, Dict, Any, Optional, Tuple
import fitz
import chromadb
from chromadb.utils import embedding_functions
import requests
import warnings

def secure_filename(filename: str) -> str:
    """Secure a filename by removing unsafe characters"""
    filename = re.sub(r'[^\w\s.-]', '', filename)
    filename = re.sub(r'[-\s]+', '-', filename)
    return filename.strip('-')

warnings.filterwarnings('ignore')
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GLOG_minloglevel'] = '2'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['ANONYMIZED_TELEMETRY'] = 'False'

SYSTEM_PROMPT = """You are an AI assistant that answers questions about documents.

Read and understand the context provided, then answer the user's question in your own words.

Guidelines:
- Be VERY SHORT and CONCISE
- Provide only essential information
- Speak naturally and conversationally
- Synthesize information rather than quoting text

Keep your answer brief and to the point."""

USER_MESSAGE_TEMPLATE = """CONTEXT INFORMATION:
{context}

{conversation_context}

CURRENT QUESTION:
{query_text}

Answer the user's question based on the context above.
Provide a direct, concise answer in your own words.
Keep it brief and natural."""

class PDFScreenshotProcessor:
    def __init__(self, dpi: int = 300):
        self.dpi = dpi

    def convert_pdf_to_images(self, pdf_path: str) -> List[Image.Image]:
        images = []
        pdf_document = fitz.open(pdf_path)
        for page_number in range(len(pdf_document)):
            page = pdf_document.load_page(page_number)
            pix = page.get_pixmap(matrix=fitz.Matrix(self.dpi/72, self.dpi/72))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        pdf_document.close()
        return images

    def extract_text_from_image(self, image: Image.Image) -> str:
        text = pytesseract.image_to_string(image)
        return text

    def process_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        images = self.convert_pdf_to_images(pdf_path)
        pages = []
        for i, image in enumerate(images):
            page_num = i + 1
            text = self.extract_text_from_image(image)
            pages.append({
                "page_id": f"page_{uuid.uuid4()}",
                "pdf_name": os.path.basename(pdf_path),
                "page_num": page_num,
                "text": text,
                "image": image
            })
        return pages

    def extract_tables_from_pages(self, pages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        table_extractor = TableExtractor()
        tables_by_page = {}
        for page in pages:
            page_tables = table_extractor.extract_tables_from_image(page['image'])
            if page_tables:
                for table in page_tables:
                    table['page_num'] = page['page_num']
                    table['pdf_name'] = page['pdf_name']
                tables_by_page[str(page['page_num'])] = page_tables
        return tables_by_page


class ChunkStrategy:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        cleaned_text = self._clean_text(text)
        paragraphs = cleaned_text.split('\n\n')
        paragraphs = [p for p in paragraphs if p.strip()]
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            if len(current_chunk) + len(para) > self.chunk_size and current_chunk:
                chunk_id = f"chunk_{uuid.uuid4()}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": current_chunk.strip(),
                    "metadata": {**metadata, "chunk_id": chunk_id}
                })
                words = current_chunk.split()
                overlap_text = " ".join(words[-self.chunk_overlap:]) if len(words) > self.chunk_overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
        
        if current_chunk:
            chunk_id = f"chunk_{uuid.uuid4()}"
            chunks.append({
                "chunk_id": chunk_id,
                "text": current_chunk.strip(),
                "metadata": {**metadata, "chunk_id": chunk_id}
            })
        
        return chunks

    def _clean_text(self, text: str) -> str:
        cleaned = re.sub(r'\s+', ' ', text)
        cleaned = cleaned.replace('|', 'I')
        cleaned = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', cleaned)
        cleaned = ''.join(c for c in cleaned if c.isprintable() or c in '\n\t')
        
        wrapped = []
        for line in cleaned.split('\n'):
            if len(line) > 100:
                wrapped.extend(textwrap.wrap(line, width=100))
            else:
                wrapped.append(line)
        
        return '\n'.join(wrapped)


class VectorDatabaseManager:
    def __init__(self, collection_name: str = "pdf_screenshots"):
        self.persist_directory = f"storage/chroma_db_{collection_name}"
        self.collection_name = collection_name
        
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
        except:
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
    
    def collection_exists(self) -> bool:
        try:
            count = self.collection.count()
            return count > 0
        except:
            return False

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        if not chunks:
            return
        
        batch_size = 10
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            ids = [chunk["chunk_id"] for chunk in batch]
            documents = [chunk["text"] for chunk in batch]
            metadatas = [chunk["metadata"] for chunk in batch]
            
            for m in metadatas:
                for k, v in m.items():
                    if not isinstance(v, (str, int, float, bool)):
                        m[k] = str(v)
            
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )

    def query(self, query_text: str, n_results: int = 5, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        query_args = {
            "query_texts": [query_text],
            "n_results": min(n_results, 20)
        }
        if filters:
            query_args["where"] = filters
        
        results = self.collection.query(**query_args)
        return results


class TableExtractor:
    def __init__(self):
        self.confidence_threshold = 85

    def extract_tables_from_image(self, image: Image.Image) -> List[Dict[str, Any]]:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        tables = []
        current_table = None
        current_row = []
        last_line = -1
        
        for i in range(len(data['text'])):
            if not data['text'][i].strip() or int(data['conf'][i]) < self.confidence_threshold:
                continue
            
            if data['line_num'][i] != last_line:
                if current_row and current_table is not None:
                    current_table['rows'].append(current_row)
                current_row = []
                last_line = data['line_num'][i]
            
            if self._is_likely_table_header(data['text'][i]):
                if current_table is not None and current_table['rows']:
                    tables.append(current_table)
                current_table = {
                    'table_id': f"table_{uuid.uuid4()}",
                    'header': data['text'][i],
                    'rows': [],
                    'bbox': [data['left'][i], data['top'][i], data['width'][i], data['height'][i]]
                }
            
            if current_table is not None:
                current_row.append(data['text'][i])
        
        if current_row and current_table is not None:
            current_table['rows'].append(current_row)
            tables.append(current_table)
        
        structured_tables = []
        for table in tables:
            if len(table['rows']) > 1:
                structured = self._structure_table(table)
                if structured:
                    structured_tables.append(structured)
        
        return structured_tables

    def _is_likely_table_header(self, text: str) -> bool:
        header_keywords = ['table', 'summary', 'total', 'year', 'quarter', 'month', 
                          'item', 'description', 'amount', 'value', 'date', 'name']
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in header_keywords)

    def _structure_table(self, table: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not table['rows'] or len(table['rows']) < 2:
            return None
        
        if len(table['rows'][0]) > 1:
            headers = table['rows'][0]
        else:
            headers = [f"Column {i+1}" for i in range(max(len(row) for row in table['rows']))]
        
        data_rows = []
        for row in table['rows'][1:]:
            if len(row) > 0:
                padded_row = row + [''] * (len(headers) - len(row))
                data_rows.append(padded_row[:len(headers)])
        
        return {
            'table_id': table['table_id'],
            'title': table['header'],
            'headers': headers,
            'data': data_rows
        }


class RagSystem:
    def __init__(self, model: str = "llama3.1:8b", base_url: str = "http://localhost:11434", pdf_filename: str = None):
        self.pdf_processor = PDFScreenshotProcessor()
        self.chunker = ChunkStrategy(chunk_size=1000, chunk_overlap=200)
        
        collection_name = "multi_pdf_collection"
        self.vector_db = VectorDatabaseManager(collection_name=collection_name)
        
        self.tables_by_page = {}
        self.pdf_paths = []
        self.pdf_names = []
        self.conversation_history = []
        self.model = model
        self.base_url = base_url

    def index_pdf(self, pdf_path: str) -> None:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        pdf_filename = os.path.basename(pdf_path)
        
        if pdf_path in self.pdf_paths:
            print(f"PDF {pdf_filename} is already indexed")
            return
        
        print(f"Embedding {pdf_filename}...")
        pages = self.pdf_processor.process_pdf(pdf_path)
        
        pdf_tables = self.pdf_processor.extract_tables_from_pages(pages)
        for page_num, tables in pdf_tables.items():
            key = f"{pdf_filename}_page_{page_num}"
            self.tables_by_page[key] = tables
        
        tables_json_path = f"{os.path.splitext(pdf_path)[0]}_tables.json"
        with open(tables_json_path, 'w') as f:
            json.dump(pdf_tables, f, indent=2)
        
        all_chunks = []
        for page in pages:
            metadata = {
                "pdf_name": page["pdf_name"],
                "page_num": page["page_num"],
                "page_id": page["page_id"],
                "has_tables": str(page["page_num"]) in pdf_tables,
                "pdf_path": pdf_path
            }
            page_chunks = self.chunker.chunk_text(page["text"], metadata)
            all_chunks.extend(page_chunks)
        
        self.vector_db.add_chunks(all_chunks)
        
        self.pdf_paths.append(pdf_path)
        self.pdf_names.append(pdf_filename)
        
        print(f"Embedding complete for {pdf_filename}")

    def query(self, query_text: str, n_results: int = 1) -> str:
        print("\n" + "="*80)
        print("USER QUESTION:")
        print(query_text)
        print("="*80)
        
        filters = {}
        if "page" in query_text.lower():
            match = re.search(r'page\s+(\d+)', query_text.lower())
            if match:
                filters["page_num"] = int(match.group(1))
        
        results = self.vector_db.query(query_text, n_results=n_results, filters=filters)
        
        if not results["ids"][0]:
            response = "Sorry, I couldn't find any relevant information in the document to answer your question."
            self.conversation_history.append({
                "question": query_text,
                "answer": response
            })
            return response
        
        context_parts = []
        page_nums = set()
        
        print("\nRETRIEVED CHUNKS:")
        print("-"*80)
        for i in range(len(results["ids"][0])):
            document = results["documents"][0][i]
            metadata = results["metadatas"][0][i]
            page_num = metadata.get('page_num', 'unknown')
            
            print(f"\nChunk {i+1} (Page {page_num}):")
            print(document[:300] + "..." if len(document) > 300 else document)
            print("-"*80)
            
            if page_num != 'unknown':
                page_nums.add(str(page_num))
            
            context_part = f"--- EXCERPT FROM {metadata.get('pdf_name', 'document')}, PAGE {page_num} ---\n"
            context_part += document
            context_part += "\n---\n"
            context_parts.append(context_part)
        
        table_context = ""
        for i in range(len(results["ids"][0])):
            metadata = results["metadatas"][0][i]
            pdf_name = metadata.get('pdf_name', '')
            page_num = str(metadata.get('page_num', ''))
            
            table_key = f"{pdf_name}_page_{page_num}"
            if table_key in self.tables_by_page:
                tables = self.tables_by_page[table_key]
                for table in tables:
                    table_context += f"\n--- TABLE FROM {pdf_name}, PAGE {page_num}: {table.get('title', 'Untitled Table')} ---\n"
                    if 'headers' in table:
                        table_context += " | ".join(table['headers']) + "\n"
                        table_context += "-" * (sum(len(h) for h in table['headers']) + (len(table['headers'])-1) * 3) + "\n"
                    if 'data' in table:
                        for row in table['data']:
                            table_context += " | ".join(row) + "\n"
                    table_context += "---\n"
        
        context = "\n".join(context_parts)
        if table_context:
            context += "\n\nTABLE DATA:\n" + table_context
        
        conversation_context = ""
        if self.conversation_history:
            conversation_context = "\n\nPREVIOUS CONVERSATION:\n"
            for i, exchange in enumerate(self.conversation_history[-3:]):
                conversation_context += f"Question {i+1}: {exchange['question']}\n"
                conversation_context += f"Answer {i+1}: {exchange['answer']}\n\n"
        
        user_message = USER_MESSAGE_TEMPLATE.format(
            context=context,
            conversation_context=conversation_context,
            query_text=query_text
        )
        
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": f"{SYSTEM_PROMPT}\n\n{user_message}",
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 1500
                    }
                }
            )
            response.raise_for_status()
            answer = response.json()["response"]
            
            print("\nLLM RESPONSE:")
            print("="*80)
            print(answer)
            print("="*80 + "\n")
            
            if self.pdf_names:
                source_pdfs = set()
                for i in range(len(results["ids"][0])):
                    metadata = results["metadatas"][0][i]
                    pdf_name = metadata.get('pdf_name', '')
                    if pdf_name:
                        source_pdfs.add(pdf_name)
                
                if source_pdfs:
                    if len(source_pdfs) == 1:
                        answer += f"\n\nSource document: {list(source_pdfs)[0]}"
                    else:
                        answer += f"\n\nSource documents: {', '.join(sorted(source_pdfs))}"
                
                if page_nums:
                    answer += "\nRelevant pages: " + ", ".join(f"Page {p}" for p in sorted(page_nums, key=int))
            
            self.conversation_history.append({
                "question": query_text,
                "answer": answer
            })
            
            return answer
            
        except Exception as e:
            error_msg = f"Sorry, I encountered an error while generating a response: {str(e)}"
            self.conversation_history.append({
                "question": query_text,
                "answer": error_msg
            })
            return error_msg


class RagService:
    def __init__(self):
        self.rag_system: Optional[RagSystem] = None
        self.upload_folder = 'storage/uploads/pdfs'
        os.makedirs(self.upload_folder, exist_ok=True)
    
    def upload_pdfs(self, files) -> Tuple[bool, dict]:
        processed_files = []
        failed_files = []
        
        if self.rag_system is None:
            self.rag_system = RagSystem(model="llama3.1:8b")
        
        file_list = files if isinstance(files, list) else [files]
        
        for file in file_list:
            try:
                secure_name = secure_filename(file.filename)
                filepath = os.path.join(self.upload_folder, secure_name)
                file.save(filepath)
                
                self.rag_system.index_pdf(filepath)
                processed_files.append(secure_name)
                
            except Exception as e:
                failed_files.append({
                    "filename": file.filename,
                    "error": str(e)
                })
        
        success = len(failed_files) == 0
        file_count = len(processed_files)
        
        if file_count == 1:
            message = f"Successfully processed 1 PDF: {processed_files[0]}"
        else:
            message = f"Successfully processed {file_count} PDFs"
        
        return success, {
            "message": message,
            "filenames": processed_files,
            "failed_files": failed_files,
            "total_processed": file_count
        }
    
    def query_documents(self, question: str) -> Tuple[bool, dict]:
        if self.rag_system is None:
            return False, {"error": "No PDF has been uploaded yet. Please upload a PDF first."}
        
        try:
            response = self.rag_system.query(question)
            return True, {"answer": response}
        except Exception as e:
            return False, {"error": f"Error processing query: {str(e)}"}
    
    def get_status(self) -> dict:
        return {
            "document_loaded": self.rag_system is not None and len(self.rag_system.pdf_names) > 0,
            "pdf_names": self.rag_system.pdf_names if self.rag_system else []
        }
    
    def clear_system(self) -> dict:
        self.rag_system = None
        return {
            "success": True,
            "message": "RAG system cleared"
        }