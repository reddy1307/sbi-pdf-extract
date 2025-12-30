from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import re
import pandas as pd
import tempfile
import os

app = FastAPI(title="Bank Statement Parser API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# DESCRIPTION EXTRACTION
# -------------------------
def extract_description(txn):
    patterns = [
        r"/(?:CR|DR)/\d+/([^/]+)",
        r"UPI/(?:CR|DR)/\d+/([^/]+)",
        r"TRANSFER (?:FROM|TO)\s+\d+\s+(UPI/(?:CR|DR)/\d+/([^/]+))"
    ]

    for pattern in patterns:
        match = re.search(pattern, txn, re.IGNORECASE)
        if match:
            desc = match.group(1)
            if "UPI/" in desc:
                name_match = re.search(r"/([^/]+)$", desc)
                if name_match:
                    return name_match.group(1).strip()
            return desc.strip()

    return "Unknown"

# -------------------------
# EXPANDED CATEGORIZATION
# -------------------------
def categorize(desc, txn_type):
    desc = desc.lower()

    if txn_type == "CREDIT":
        return "Income / Transfer In"

    categories = {
        "Food & Dining": [
            "zomato", "swiggy", "ubereats", "domino", "pizza",
            "kfc", "mcd", "restaurant", "cafe", "hotel",
            "eatfit", "biryani", "food"
        ],

        "Groceries": [
            "bigbasket", "blinkit", "zepto", "instamart",
            "dmart", "reliance", "grocery", "kirana"
        ],

        "Shopping": [
            "amazon", "flipkart", "myntra", "ajio",
            "meesho", "snapdeal", "store", "mall", "retail"
        ],

        "Travel": [
            "uber", "ola", "rapido", "irctc", "redbus",
            "makemytrip", "yatra", "goibibo",
            "flight", "train", "bus"
        ],

        "Fuel": [
            "petrol", "diesel", "fuel",
            "indian oil", "hp", "bharat petroleum", "shell"
        ],

        "Recharge & Bills": [
            "airtel", "jio", "vi", "vodafone", "bsnl",
            "recharge", "mobile bill", "postpaid", "prepaid"
        ],

        "Utilities": [
            "electricity", "power", "water", "gas",
            "bill", "broadband", "wifi", "internet"
        ],

        "Entertainment": [
            "netflix", "prime", "hotstar", "spotify",
            "bookmyshow", "sony liv", "zee5",
            "music", "movie"
        ],

        "Healthcare": [
            "hospital", "clinic", "pharmacy", "medical",
            "apollo", "medplus", "1mg", "pharmeasy", "doctor"
        ],

        "Education": [
            "udemy", "coursera", "byju", "unacademy",
            "college", "school", "exam", "fees", "tuition"
        ],

        "Banking & Finance": [
            "emi", "loan", "interest", "insurance",
            "mutual fund", "sip", "credit card", "bank charges"
        ],

        "Transfer Out": [
            "paid to", "transfer to", "upi", "neft", "imps"
        ]
    }

    for category, keywords in categories.items():
        if any(keyword in desc for keyword in keywords):
            return category

    return "Other Expense"

# -------------------------
# GROUP MULTI-LINE TXNS
# -------------------------
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

# -------------------------
# PARSE SINGLE TRANSACTION
# -------------------------
def parse_transaction(txn):
    txn = re.sub(r'\s+', ' ', txn.strip())

    date_match = re.search(r"(\d{2}\s+[A-Z]{3}\s+\d{4})", txn)
    date = None
    if date_match:
        date = pd.to_datetime(date_match.group(1), format="%d %b %Y")

    numbers = re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", txn)
    nums = [float(x.replace(",", "")) for x in numbers]

    amount = 0.0
    txn_type = "UNKNOWN"

    if "TRANSFER TO" in txn.upper() or "/DR/" in txn.upper():
        txn_type = "DEBIT"
        amount = nums[1] if len(nums) >= 2 else 0.0

    elif "TRANSFER FROM" in txn.upper() or "/CR/" in txn.upper():
        txn_type = "CREDIT"
        amount = nums[1] if len(nums) >= 2 else 0.0

    utr = None
    utr_patterns = [
        r"(?:/CR/|/DR/)(\d{6,})",
        r"TRANSFER (?:FROM|TO)\s+(\d{10,})",
        r"\b(\d{12,})\b",
        r"Ref No[\.:]*\s*(\d{6,})"
    ]

    for pattern in utr_patterns:
        match = re.search(pattern, txn)
        if match:
            utr = match.group(1)
            break

    desc = extract_description(txn)

    return {
        "date": date.strftime("%Y-%m-%d") if date is not None else None,
        "amount": round(amount, 2),
        "type": txn_type,
        "description": desc,
        "category": categorize(desc, txn_type),
        "utr": utr
    }

# -------------------------
# API ENDPOINT
# -------------------------
@app.post("/upload")
async def parse_pdf(
    file: UploadFile = File(...),
    password: str = Form(...)
):
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
    except Exception as e:
        os.unlink(pdf_path)
        return {"error": f"Invalid PDF or password: {str(e)}"}

    footer_phrases = [
        "please do not share your atm",
        "bank never ask for such information",
        "computer generated statement",
        "does not require a signature",
        "balance as on"
    ]

    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(fp in line.lower() for fp in footer_phrases):
            break
        clean_lines.append(line)

    grouped = group_transactions(clean_lines)

    transactions = []
    for txn in grouped:
        parsed = parse_transaction(txn)
        if parsed["amount"] > 0:
            transactions.append(parsed)

    os.unlink(pdf_path)

    return {
        "transactions": transactions,
        "count": len(transactions)
    }
