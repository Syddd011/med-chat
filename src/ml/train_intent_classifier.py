# src/ml/train_intent_classifier.py

"""
Train an intent classification model for med-chat.

Standalone version:
- Does NOT import src.ml.config (to avoid import issues).
- Computes all paths locally.
"""

import os

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, accuracy_score
from sklearn.svm import LinearSVC
import joblib

# ----------------------------------------------------
#  PATH SETUP (no config import)
# ----------------------------------------------------

# __file__ = .../med-chat/src/ml/train_intent_classifier.py
THIS_FILE_DIR = os.path.dirname(os.path.abspath(__file__))      # .../src/ml
SRC_DIR = os.path.dirname(THIS_FILE_DIR)                        # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)                         # .../med-chat

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

INTENT_DATASET_PATH = os.path.join(DATA_DIR, "intent_dataset.csv")
INTENT_MODEL_PATH = os.path.join(MODELS_DIR, "intent_classifier.joblib")
INTENT_VECTORIZER_PATH = os.path.join(MODELS_DIR, "intent_vectorizer.joblib")

INTENT_LABELS = [
    "general_info",
    "symptoms",
    "medication_info",
    "lifestyle",
    "emergency_like",
    "other",
]


def load_dataset(path: str) -> pd.DataFrame:
    """Load the intent dataset from CSV."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Intent dataset not found at {path}. "
            f"Make sure you created data/intent_dataset.csv (Step 2.1)."
        )

    df = pd.read_csv(path)

    # Basic validation
    expected_cols = {"text", "label"}
    if not expected_cols.issubset(df.columns):
        raise ValueError(
            f"Dataset must contain columns {expected_cols}, "
            f"but has {list(df.columns)}"
        )

    # Drop rows with missing data
    df = df.dropna(subset=["text", "label"])

    # Filter to known labels only
    df = df[df["label"].isin(INTENT_LABELS)]

    if df.empty:
        raise ValueError("Dataset is empty after filtering. Check your labels.")

    return df


def train_intent_classifier(df: pd.DataFrame):
    """Train a TF-IDF + LinearSVC intent classifier."""
    X = df["text"].astype(str).values
    y = df["label"].astype(str).values

    # Split into train/validation
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # TF-IDF vectorizer
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),  # unigrams + bigrams
        min_df=1,
        max_df=0.9,
        sublinear_tf=True,
        strip_accents="unicode",
    )

    # Fit vectorizer on training text
    X_train_vec = vectorizer.fit_transform(X_train)
    X_val_vec = vectorizer.transform(X_val)

    # Classifier: LinearSVC (strong for sparse text)
    clf = LinearSVC()

    # Train
    clf.fit(X_train_vec, y_train)

    # Evaluate
    y_pred = clf.predict(X_val_vec)
    acc = accuracy_score(y_val, y_pred)
    print("=" * 60)
    print("Validation Accuracy:", round(acc * 100, 2), "%")
    print("-" * 60)
    print("Classification Report:")
    print(classification_report(y_val, y_pred, labels=INTENT_LABELS))
    print("=" * 60)

    return vectorizer, clf


def save_artifacts(vectorizer, clf):
    """Save trained vectorizer and classifier to disk."""
    joblib.dump(clf, INTENT_MODEL_PATH)
    joblib.dump(vectorizer, INTENT_VECTORIZER_PATH)

    print(f"Saved intent classifier to: {INTENT_MODEL_PATH}")
    print(f"Saved TF-IDF vectorizer to: {INTENT_VECTORIZER_PATH}")


def main():
    print("Project root:", PROJECT_ROOT)
    print("Loading dataset from:", INTENT_DATASET_PATH)
    df = load_dataset(INTENT_DATASET_PATH)

    print(f"Loaded {len(df)} samples.")
    print("Training intent classifier...")
    vectorizer, clf = train_intent_classifier(df)

    print("Saving model and vectorizer...")
    save_artifacts(vectorizer, clf)
    print("Done.")


if __name__ == "__main__":
    main()
