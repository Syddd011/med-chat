"""Clean the intent_dataset.csv — removes comment lines and blanks, then re-saves."""
import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
path = os.path.join(DATA_DIR, "intent_dataset.csv")

df = pd.read_csv(path, comment='#')
df.columns = ['text', 'label']
df = df.dropna()
df['text'] = df['text'].astype(str).str.strip()
df['label'] = df['label'].astype(str).str.strip()
df = df[df['text'] != '']
df = df[~df['text'].str.startswith('#')]
df.to_csv(path, index=False)
print(f"Cleaned dataset saved: {len(df)} rows")
print(df['label'].value_counts().to_string())
