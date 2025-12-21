from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import re
import pandas as pd
import tempfile
import os

app = FastAPI(title="Bank Statement Parser API")

# Enable CORS (important for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Helpers
# -------------------------

def extract_description(txn):
    match = re.search(r"/(?:CR|DR)/\d+/([^/]+)", txn, re.IGNORECASE)
    return match.group(1).strip() if match else "Unknown"

def categorize(desc, txn_type):
    desc = desc.lower()

    if txn_type == "CREDIT":
        return "Income / Transfer In"

    categories = {
        "Recharge": ["airtel", "jio", "vi", "vodafone", "bsnl"],
        "Food & Dining": ["zomato", "swiggy", "pizza", "restaurant", "hotel"],
        "Fuel": ["petrol", "diesel", "fuel"],
        "Shopping": ["amazon", "flipkart", "myntra", "store"],
        "Groceries": ["dmart", "bigbasket", "zepto", "instamart"],
        "Travel": ["uber", "ola", "rapido", "irctc"],
        "Entertainment": ["netflix", "prime", "hotstar"],
        "Utilities": ["electricity", "water", "gas", "bill"],
        "Healthcare": ["hospital", "pharmacy", "medical"],
        "Banking & Finance": ["emi", "loan", "insurance"],
        "Transfer Out": ["paid to"]
    }

    for cat, keywords in categories.items():
        if any(k in desc for k in keywords):
            return cat

    return "Other Expense"

def group_transactions(lines):
    transactions = []
    current = []
    date_pattern = re.compile(r"^\d{2}\s+[A-Z]{3}\s+\d{4}")

    for line in lines:
        if date_pattern.match(line):
            if current:
                transactions.append(" ".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        transactions.append(" ".join(current))

    return transactions

def parse_transaction(txn):
    # Date
    date_match = re.search(r"(\d{2}\s+[A-Z]{3}\s+\d{4})", txn)
    date = pd.to_datetime(date_match.group(1), format="%d %b %Y") if date_match else None

    # Numbers
    nums = [float(x.replace(",", "")) for x in re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", txn)]

    amount = 0.0
    txn_type = "UNKNOWN"

    if "TRANSFER TO" in txn or "/DR/" in txn:
        txn_type = "DEBIT"
        amount = nums[-2] if len(nums) >= 2 else 0.0
    elif "TRANSFER FROM" in txn or "/CR/" in txn:
        txn_type = "CREDIT"
        amount = nums[-2] if len(nums) >= 2 else 0.0

    # UTR
    utr_match = re.search(r"(?:/CR/|/DR/|UTR\s*No[:\s]*)(\d{6,})", txn)
    utr = utr_match.group(1) if utr_match else None

    desc = extract_description(txn)

    return {
        "date": date.strftime("%d-%b-%Y") if date is not None else None,
        "description": desc,
        "type": txn_type,
        "amount": round(amount, 2),
        "category": categorize(desc, txn_type),
        "UTR_No": utr
    }

# -------------------------
# API Endpoint
# -------------------------

@app.post("/upload")
async def parse_pdf(
    file: UploadFile = File(...),
    password: str = Form(...)
):
    # Save PDF temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        pdf_path = tmp.name

    lines = []

    try:
        with pdfplumber.open(pdf_path, password=password) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines.extend(text.split("\n"))
    except Exception:
        os.unlink(pdf_path)
        return {"error": "Invalid PDF or password"}

    # Remove header
    start = next(
        (i for i, l in enumerate(lines) if re.search(r"Date\s+Details\s+Ref\s+No", l, re.I)),
        None
    )
    if start:
        lines = lines[start + 1:]

    # Clean lines
    footer_phrases = [
        "please do not share your atm",
        "bank never ask for such information",
        "computer generated statement",
        "does not require a signature"
    ]

    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.search(r"Date\s+Details\s+Ref\s+No", line, re.I):
            continue
        if any(fp in line.lower() for fp in footer_phrases):
            break
        clean_lines.append(line)

    grouped = group_transactions(clean_lines)
    result = [parse_transaction(txn) for txn in grouped]

    os.unlink(pdf_path)
    return result[1:]
