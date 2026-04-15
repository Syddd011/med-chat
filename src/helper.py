from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
try:
    from langchain_huggingface import HuggingFaceEmbeddings          # langchain>=0.2.2
except ImportError:
    from langchain_community.embeddings import HuggingFaceEmbeddings  # fallback
from typing import List
from langchain_core.documents import Document


# Extract Data From the PDF File
import os

def load_pdf_files(data=None):
    """Load PDFs and TXT knowledge files from a directory.

    If `data` is None, use <repo_root>/data.
    If `data` is relative, resolve it against repository root.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    if data is None:
        data_dir = os.path.join(repo_root, "data")
    elif os.path.isabs(data):
        data_dir = data
    else:
        data_dir = os.path.abspath(os.path.join(repo_root, data))

    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f"Directory not found: {data_dir} (cwd={os.getcwd()})")

    all_documents = []

    # Load PDFs one-by-one (so one bad file doesn't kill the rest)
    try:
        import glob as _glob
        pdf_files = _glob.glob(os.path.join(data_dir, "*.pdf"))
        pdf_docs = []
        for pdf_path in pdf_files:
            # Skip tiny files — likely HTML error pages (< 2 KB)
            if os.path.getsize(pdf_path) < 2048:
                print(f"  Skipping tiny/corrupted file: {os.path.basename(pdf_path)}")
                continue
            try:
                loader = PyPDFLoader(pdf_path)
                pages  = loader.load()
                pdf_docs.extend(pages)
                print(f"  Loaded PDF: {os.path.basename(pdf_path)} ({len(pages)} pages)")
            except Exception as pdf_err:
                print(f"  Skipping corrupted PDF {os.path.basename(pdf_path)}: {pdf_err}")
        all_documents.extend(pdf_docs)
        print(f"  Loaded {len(pdf_docs)} pages from PDF files.")
    except Exception as e:
        print(f"  Warning: PDF loading error: {e}")

    # Load TXT knowledge files
    txt_files = [f for f in os.listdir(data_dir) if f.endswith(".txt")]
    for fname in txt_files:
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            doc = Document(page_content=content, metadata={"source": fpath})
            all_documents.append(doc)
            print(f"  Loaded TXT: {fname} ({len(content)} chars)")
        except Exception as e:
            print(f"  Warning: Could not load {fname}: {e}")

    print(f"  Total documents loaded: {len(all_documents)}")
    return all_documents




def filter_to_minimal_docs(docs: List[Document]) -> List[Document]:
    """
    Given a list of Document objects, return a new list of Document objects
    containing only 'source' in metadata and the original page_content.
    """
    minimal_docs: List[Document] = []
    for doc in docs:
        src = doc.metadata.get("source")
        minimal_docs.append(
            Document(
                page_content=doc.page_content,
                metadata={"source": src}
            )
        )
    return minimal_docs



#Split the Data into Text Chunks
def text_split(extracted_data):
    text_splitter=RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=20)
    text_chunks=text_splitter.split_documents(extracted_data)
    return text_chunks



#Download the Embeddings from HuggingFace 
def download_hugging_face_embeddings():
    embeddings=HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')  #this model return 384 dimensions
    return embeddings