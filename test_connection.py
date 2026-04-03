#!/usr/bin/env python
import socket
import urllib.request
import urllib.error

# Test DNS resolution
print("Testing DNS resolution...")
try:
    result = socket.gethostbyname('api.pinecone.io')
    print(f"✓ api.pinecone.io resolves to: {result}")
except socket.gaierror as e:
    print(f"✗ DNS resolution failed: {e}")

try:
    result = socket.gethostbyname('huggingface.co')
    print(f"✓ huggingface.co resolves to: {result}")
except socket.gaierror as e:
    print(f"✗ DNS resolution failed: {e}")

# Test HTTPS connection
print("\nTesting HTTPS connections...")
try:
    response = urllib.request.urlopen('https://api.pinecone.io', timeout=5)
    print(f"✓ Connected to api.pinecone.io (Status: {response.status})")
    response.close()
except Exception as e:
    print(f"✗ Failed to connect to api.pinecone.io: {type(e).__name__}: {e}")

try:
    response = urllib.request.urlopen('https://huggingface.co', timeout=5)
    print(f"✓ Connected to huggingface.co (Status: {response.status})")
    response.close()
except Exception as e:
    print(f"✗ Failed to connect to huggingface.co: {type(e).__name__}: {e}")
