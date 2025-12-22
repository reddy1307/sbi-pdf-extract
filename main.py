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



def extract_description(txn):
   
    patterns = [
        r"/(?:CR|DR)/\d+/([^/]+)", 
        r"UPI/(?:CR|DR)/\d+/([^/]+)", 
        r"TRANSFER (?:FROM|TO)\s+\d+\s+(UPI/(?:CR|DR)/\d+/([^/]+))" 
    ]
    
    for pattern in patterns:
        match = re.search(pattern, txn, re.IGNORECASE)
        if match:
          
            desc = match.group(1) if match.lastindex >= 1 else "Unknown"
            
            if "UPI/" in desc:
               
                name_match = re.search(r"/([^/]+)$", desc)
                if name_match:
                    return name_match.group(1).strip()
            return desc.strip()
    
    return "Unknown"

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
    
    txn = re.sub(r'\s+', ' ', txn.strip())
    
    
    print(f"Parsing transaction: {txn}")
    
    
    date_match = re.search(r"(\d{2}\s+[A-Z]{3}\s+\d{4})", txn)
    date = None
    if date_match:
        try:
          
            date_str = date_match.group(1)
            date = pd.to_datetime(date_str, format="%d %b %Y")
        except Exception as e:
            print(f"Error parsing date {date_match.group(1)}: {e}")
    
   
    all_numbers = re.findall(r"\d+(?:,\d+)*(?:\.\d+)?", txn)
    nums = [float(x.replace(",", "")) for x in all_numbers]
    
    
  
    amount = 0.0
    txn_type = "UNKNOWN"
    
    if "TRANSFER TO" in txn.upper() or "/DR/" in txn.upper():
        txn_type = "DEBIT"
        
        debit_match = re.search(r"TRANSFER TO\s+\d+\s+-\s+(\d+(?:,\d+)*(?:\.\d+)?)", txn)
        if debit_match:
            amount = float(debit_match.group(1).replace(",", ""))
        elif len(nums) >= 2:
           
            if len(nums) == 2:
                amount = nums[0]  
            elif len(nums) >= 3:
                
                amount = nums[1]  
                
    elif "TRANSFER FROM" in txn.upper() or "/CR/" in txn.upper():
        txn_type = "CREDIT"
        
        credit_match = re.search(r"TRANSFER FROM\s+\d+\s+-\s+-\s+(\d+(?:,\d+)*(?:\.\d+)?)", txn)
        if credit_match:
            amount = float(credit_match.group(1).replace(",", ""))
        elif len(nums) >= 2:
            if len(nums) == 2:
                amount = nums[0]  
            elif len(nums) >= 3:
                amount = nums[1] 

    
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
    
    
    result = {
        "amount": round(amount, 2),
        "type": txn_type,
        "date": date.strftime("%d-%b-%Y") if date is not None else None,
        "description": desc,
        "category": categorize(desc, txn_type),
        "utr": utr  
    }
    
    return result


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

    start = None
    for i, line in enumerate(lines):
        if re.search(r"Date\s+Details\s+Ref\s+No", line, re.I):
            start = i
            break
    
    if start is not None:
        lines = lines[start + 1:]

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
        if re.search(r"Date\s+Details\s+Ref\s+No", line, re.I):
            continue
        if any(fp in line.lower() for fp in footer_phrases):
            break
        clean_lines.append(line)

    
   
    grouped = group_transactions(clean_lines)
   
   
    result = []
    for txn in grouped:
        parsed = parse_transaction(txn)
        if parsed["amount"] > 0:  
            result.append(parsed)
    
    os.unlink(pdf_path)
    
   
    return result
