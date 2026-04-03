from dotenv import load_dotenv
import os
import time
from src.helper import load_pdf_files, filter_to_minimal_docs, text_split, download_hugging_face_embeddings
from pinecone import Pinecone
from pinecone import ServerlessSpec 
from langchain_pinecone import PineconeVectorStore

load_dotenv()

PINECONE_API_KEY=os.environ.get('PINECONE_API_KEY')
OPENAI_API_KEY=os.environ.get('OPENAI_API_KEY')

os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

print("Loading PDF files...")
extracted_data=load_pdf_files(data='data/')
print(f"Loaded {len(extracted_data)} documents")

print("Filtering documents...")
filter_data = filter_to_minimal_docs(extracted_data)

print("Splitting text chunks...")
text_chunks=text_split(filter_data)
print(f"Created {len(text_chunks)} text chunks")

print("Downloading embeddings model (this may take a moment on first run)...")
embeddings = download_hugging_face_embeddings()
print("Embeddings ready!")

pinecone_api_key = PINECONE_API_KEY
pc = Pinecone(api_key=pinecone_api_key)

index_name = "medical-chatbot"  # change if desired

# Check if index exists with retry logic
max_retries = 3
for attempt in range(max_retries):
    try:
        print(f"Checking if index '{index_name}' exists...")
        if pc.has_index(index_name):
            print(f"Index '{index_name}' already exists. Deleting it to prevent duplicate data...")
            pc.delete_index(index_name)
            time.sleep(10) # wait for deletion to propagate
            
        print(f"Creating index '{index_name}'...")
        pc.create_index(
            name=index_name,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print(f"Index '{index_name}' created successfully!")
        break
    except Exception as e:
        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 5
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            print(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
        else:
            print(f"Failed after {max_retries} attempts: {e}")
            raise

print("Getting index...")
index = pc.Index(index_name)

print("Storing embeddings in Pinecone (this may take a few minutes)...")
docsearch = PineconeVectorStore.from_documents(
    documents=text_chunks,
    index_name=index_name,
    embedding=embeddings, 
)
print("Done! Embeddings stored successfully in Pinecone.")