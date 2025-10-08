import os
import re
import json
import uuid
import shutil
import textwrap
import pytesseract
from PIL import Image
import google.generativeai as genai
from typing import List, Dict, Any, Optional
import logging
import fitz
import chromadb
from chromadb.utils import embedding_functions

# Configure logging for LLM responses
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress other library logs
logging.getLogger('google').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('requests').setLevel(logging.ERROR)
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GLOG_minloglevel'] = '2'

SYSTEM_PROMPT = """You are an AI assistant specializing in answering questions about documents.
You will receive context information extracted from PDF documents and possibly structured table data, along with a question and any previous conversation history.

Your task is to:
1. Answer based ONLY on the information provided in the context
2. Keep answers human-readable, short and concise
3. If the context doesn't contain enough information, acknowledge the limitations
4. Cite specific pages when referencing information (e.g., "According to page 3...")
5. When referencing tables, cite the table title and page number
6. If there are OCR errors in the context, try to infer the correct meaning
7. Explain concepts simply and clearly
8. Don't copy text directly from context - interpret and explain the meaning
9. Include a confidence score (0-100%) at the end of your response
10. Consider previous conversation when relevant for follow-up questions

Remember to cite your sources clearly using page numbers in the format: [Page X]"""

USER_MESSAGE_TEMPLATE = """CONTEXT INFORMATION:
{context}

{conversation_context}

CURRENT QUESTION:
{query_text}

Please answer the question based on the provided context information.
Format your answer with clear citations to page numbers in [Page X] format.
If tables are relevant to the answer, refer to them specifically.
If this appears to be a follow-up to a previous question, take that previous into account.
End your response with a confidence score (0-100%) that reflects how well the context answers the question."""


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
        self.persist_directory = f"chroma_db_{collection_name}"
        if os.path.exists(self.persist_directory):
            shutil.rmtree(self.persist_directory)
        
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.client.create_collection(
            name=collection_name,
            embedding_function=self.embedding_function
        )

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
    def __init__(self, gemini_api_key: str, model: str = "gemini-2.0-flash-exp"):
        self.pdf_processor = PDFScreenshotProcessor()
        self.chunker = ChunkStrategy(chunk_size=1000, chunk_overlap=200)
        self.vector_db = VectorDatabaseManager(collection_name="pdf_screenshots")
        self.tables_by_page = {}
        self.pdf_path = None
        self.conversation_history = []
        self.model_name = model
        
        # Gemini setup
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel(model)

    def index_pdf(self, pdf_path: str) -> None:
        print("Embedding uploaded data...")
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        self.pdf_path = pdf_path
        pages = self.pdf_processor.process_pdf(pdf_path)
        self.tables_by_page = self.pdf_processor.extract_tables_from_pages(pages)
        
        tables_json_path = f"{os.path.splitext(pdf_path)[0]}_tables.json"
        with open(tables_json_path, 'w') as f:
            json.dump(self.tables_by_page, f, indent=2)
        
        all_chunks = []
        for page in pages:
            metadata = {
                "pdf_name": page["pdf_name"],
                "page_num": page["page_num"],
                "page_id": page["page_id"],
                "has_tables": str(page["page_num"]) in self.tables_by_page
            }
            page_chunks = self.chunker.chunk_text(page["text"], metadata)
            all_chunks.extend(page_chunks)
        
        self.vector_db.add_chunks(all_chunks)
        self.conversation_history = []
        print("Data embedding complete")

    def query(self, query_text: str, n_results: int = 5) -> str:
        # Check for page-specific filters
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
        
        # Process retrieved chunks
        context_parts = []
        page_nums = set()
        
        for i in range(len(results["ids"][0])):
            document = results["documents"][0][i]
            metadata = results["metadatas"][0][i]
            page_num = metadata.get('page_num', 'unknown')
            
            if page_num != 'unknown':
                page_nums.add(str(page_num))
            
            context_part = f"--- EXCERPT FROM {metadata.get('pdf_name', 'document')}, PAGE {page_num} ---\n"
            context_part += document
            context_part += "\n---\n"
            context_parts.append(context_part)
        
        # Process tables
        table_context = ""
        for page_num in page_nums:
            if page_num in self.tables_by_page:
                tables = self.tables_by_page[page_num]
                for table in tables:
                    table_context += f"\n--- TABLE FROM PAGE {page_num}: {table.get('title', 'Untitled Table')} ---\n"
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
        
        # Build conversation context
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
            # Make request to Gemini
            response = self.model.generate_content(
                f"{SYSTEM_PROMPT}\n\n{user_message}",
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=1500,
                    temperature=0.2
                )
            )
            
            answer = response.text
            
            if self.pdf_path:
                pdf_filename = os.path.basename(self.pdf_path)
                answer += f"\n\nSource document: {pdf_filename}"
                
                page_citations = re.findall(r'\[Page (\d+)\]', answer)
                if page_citations:
                    answer += "\n\nRelevant pages:"
                    for page in sorted(set(page_citations)):
                        answer += f"\n- Page {page}"
            
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
