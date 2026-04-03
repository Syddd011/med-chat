# src/ml/intent_classifier.py

"""
Runtime intent classifier for med-chat.

Loads:
- TF-IDF vectorizer
- LinearSVC classifier

Provides:
- predict_intent(text: str) -> str
"""

import os
import joblib

# ----------------------------------------------------
#  PATH SETUP (same logic as training script)
# ----------------------------------------------------
THIS_FILE_DIR = os.path.dirname(os.path.abspath(__file__))      # .../src/ml
SRC_DIR = os.path.dirname(THIS_FILE_DIR)                        # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)                         # .../med-chat

MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
INTENT_MODEL_PATH = os.path.join(MODELS_DIR, "intent_classifier.joblib")
INTENT_VECTORIZER_PATH = os.path.join(MODELS_DIR, "intent_vectorizer.joblib")

INTENT_LABELS = [
    "general_info",
    "symptoms",
    "medication_info",
    "lifestyle",
    "emergency_like",
    "other"
]

# ----------------------------------------------------
#  LOAD MODEL + VECTORIZER (lazy load)
# ----------------------------------------------------
_model = None
_vectorizer = None


def _load_artifacts():
    """Load vectorizer and classifier into memory (only once)."""
    global _model, _vectorizer

    if _model is None or _vectorizer is None:
        if not os.path.exists(INTENT_MODEL_PATH):
            raise FileNotFoundError(
                f"Model not found at {INTENT_MODEL_PATH}. Train first!"
            )
        if not os.path.exists(INTENT_VECTORIZER_PATH):
            raise FileNotFoundError(
                f"Vectorizer not found at {INTENT_VECTORIZER_PATH}. Train first!"
            )

        _model = joblib.load(INTENT_MODEL_PATH)
        _vectorizer = joblib.load(INTENT_VECTORIZER_PATH)

    return _model, _vectorizer


# ----------------------------------------------------
#  PREDICT FUNCTION
# ----------------------------------------------------
def predict_intent(text: str) -> str:
    """
    Predict the intent category for a given text message.

    Returns one of:
    - general_info
    - symptoms
    - medication_info
    - lifestyle
    - emergency_like
    - other
    """
    if not text or not text.strip():
        return "other"

    model, vectorizer = _load_artifacts()

    X = vectorizer.transform([text])
    pred = model.predict(X)[0]

    if pred not in INTENT_LABELS:
        return "other"

    return pred


# ----------------------------------------------------
#  Quick test (run: python -m src.ml.intent_classifier)
# ----------------------------------------------------
if __name__ == "__main__":
    print("Testing classifier...\n")
    sample = input("Enter text: ")
    print("Predicted intent:", predict_intent(sample))
