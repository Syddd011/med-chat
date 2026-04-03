# listener.py
import os
import time
import csv
import re

LOG_FILE = "flask.log"          # file your Flask app should write (or prints redirected here)
CSV_FILE = "interactions.csv"   # output for Power BI

# Ensure log file exists (create empty if needed)
if not os.path.exists(LOG_FILE):
    open(LOG_FILE, "a", encoding="utf-8").close()

# Ensure CSV has header
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "response"])

# Tail the log file
print(f"Listening for new logs in '{LOG_FILE}' and writing to '{CSV_FILE}'... (Ctrl+C to stop)")

def write_row(query, response):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([query, response])
    print("Logged ->", query, "||", response[:80].replace("\n"," "))

last_query = None

# open and seek to end
with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as logfile:
    logfile.seek(0, os.SEEK_END)
    while True:
        where = logfile.tell()
        line = logfile.readline()
        if not line:
            time.sleep(0.8)
            logfile.seek(where)
            continue

        line = line.strip()
        if not line:
            continue

        # Detect the printed user input line (your app prints the raw input)
        # We assume the line containing the user's text doesn't start with "Response" prefix
        # A common case: app prints the query directly: e.g. `print(input)` or `print(user_query)`
        # We mark that as last_query
        if re.match(r"^Response\s*:", line) or line.startswith("Response :"):
            # parse response after 'Response :' or 'Response:'
            # handle if format is 'Response : <text>' or 'Response :', '<text>' printed separately
            # combine into a single string
            # Examples: "Response :  This is answer"
            parts = re.split(r"Response\s*:\s*", line, maxsplit=1)
            response_text = parts[1].strip() if len(parts) > 1 else ""
            if last_query:
                write_row(last_query, response_text)
                last_query = None
            else:
                # No preceding query captured — write with empty query
                write_row("", response_text)

        else:
            # Treat as potential user query line
            # Save last non-empty line as query (simple heuristic)
            last_query = line
