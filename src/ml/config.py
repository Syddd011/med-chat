# src/ml/config.py

"""
Configuration for the ML components of the med-chat project.
Contains:
- Intent label definitions
- Paths for dataset, saved models, vectorizer, logs
"""

import os

# Base directory of the project (one level above src/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==============================
# 1. Intent Classification Setup
# ==============================

# All valid labels for the intent classifier
INTENT_LABELS = [
    "general_info",
    "symptoms",
    "medication_info",
    "lifestyle",
    "emergency_like",
    "other"
]

# Dataset for training the ML model
INTENT_DATASET_PATH = os.path.join(BASE_DIR, "data", "intent_dataset.csv")

# Where trained ML model + vectorizer will be stored
MODEL_DIR = os.path.join(BASE_DIR, "..", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

INTENT_MODEL_PATH = os.path.join(MODEL_DIR, "intent_classifier.joblib")
INTENT_VECTORIZER_PATH = os.path.join(MODEL_DIR, "intent_vectorizer.joblib")



# CSV file to log model predictions for future improvement
INTENT_LOGS_PATH = os.path.join(BASE_DIR, "data", "intent_logs.csv")
