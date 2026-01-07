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
    d = desc.lower()
    
    # Treat all credits as income
    if txn_type.upper() == "CREDIT":
        return "Income / Transfer In"

    # Check for Transfer Out patterns first (since they're specific)
    transfer_out_keywords = [
        "paid to", "transfer out", "sent to", "upi payment", "imps", 
        "neft", "rtgs", "gift", "donation", "charity", "subscription", 
        "monthly fee", "wallet", "paytm", "phonepe", "gpay", "google pay",
        "send money", "money transfer", "payment to"
    ]
    if any(keyword in d for keyword in transfer_out_keywords):
        return "Transfer Out"

    # Check categories in priority order (most specific first)
    
    # 1. Healthcare - MEDICAL STORES SHOULD GO HERE
    healthcare_keywords = [
        "medical store", "medical shop", "pharmacy", "chemist", "apollo pharmacy",
        "medplus", "wellness pharmacy", "1mg", "pharmeasy", "netmeds", "pharmacy",
        "drug store", "medicine shop", "health store", "medical", "clinic",
        "hospital", "doctor", "diagnostic", "pathology", "lab test", "healthcare",
        "surgery", "vaccine", "dental", "optical", "physiotherapy", "therapist"
    ]
    if any(keyword in d for keyword in healthcare_keywords):
        return "Healthcare"
    
    # 2. Groceries - GENERAL STORES SHOULD GO HERE
    grocery_keywords = [
        # Specific grocery brands/stores
        "jio mart", "dmart", "bigbasket", "blinkit", "zepto", "instamart",
        "grofers", "more supermarket", "spar", "nature's basket", "easyday",
        "reliance fresh", "fresh", "supermarket", "hypermarket",
        
        # General store indicators
        "general store", "kirana store", "provision store", "daily needs store",
        "convenience store", "neighborhood store", "local store",
        
        # Grocery items
        "grocer", "vegetable", "fruit", "milk", "bread", "egg", "rice",
        "wheat", "pulses", "dal", "atta", "flour", "oil", "spices",
        "snack", "biscuit", "beverage", "tea", "coffee", "sugar", "salt",
        "dairy", "butter", "cheese", "yogurt", "paneer", "meat", "fish",
        "chicken", "egg", "bakery", "pastry", "cake"
    ]
    if any(keyword in d for keyword in grocery_keywords):
        return "Groceries"
    
    # 3. Food & Dining (restaurants, cafes, food delivery)
    food_keywords = [
        "zomato", "swiggy", "dominos", "pizza hut", "mcdonald", "kfc",
        "burger king", "subway", "starbucks", "cafe coffee day", "barista",
        "restaurant", "cafe", "hotel", "eatfit", "canteen", "food",
        "dining", "lunch", "dinner", "breakfast", "coffee shop",
        "chai", "juice center", "bakery shop", "dessert", "ice cream", "fast food",
        "street food", "dhaba", "bar", "pub", "buffet", "meal", "pizzeria",
        "food court", "food truck", "eat", "dine", "bistro", "grill", "bbq"
    ]
    if any(keyword in d for keyword in food_keywords):
        return "Food & Dining"
    
    # 4. Shopping (e-commerce, retail, clothing, electronics - NOT general stores)
    shopping_keywords = [
        # E-commerce
        "amazon", "flipkart", "myntra", "ajio", "meesho", "snapdeal",
        
        # Retail chains (not grocery)
        "shoppers stop", "pantaloons", "westside", "lifestyle", "central",
        "max fashion", "brand factory", "levis", "pepe jeans", "wrangler",
        
        # Electronics
        "croma", "reliance digital", "vijay sales", "poorvika", "sangeetha",
        
        # General shopping terms (excluding store which is too generic)
        "mall", "market", "purchase", "buy", "fashion", "clothing",
        "electronics", "furniture", "home decor", "appliances", "shoes",
        "bags", "jewelry", "accessories", "watch", "cosmetics", "perfume",
        "footwear", "garment", "apparel", "textile","lenskart","eyewear"
    ]
    if any(keyword in d for keyword in shopping_keywords):
        return "Shopping"
    
    # 5. Travel
    travel_keywords = [
        "uber", "ola", "rapido", "irctc", "makemytrip", "yatra", "redbus",
        "taxi", "cab", "bus", "train", "metro", "flight", "airline",
        "railway", "travel", "booking.com", "hotel booking", "airbnb",
        "goibibo", "cleartrip", "ixigo", "expedia", "trivago", "ticket",
        "journey", "commute", "transport", "airport", "railway station"
    ]
    if any(keyword in d for keyword in travel_keywords):
        return "Travel"
    
    # 6. Fuel
    fuel_keywords = [
        "petrol", "diesel", "fuel", "oil", "indian oil", "bharat petroleum",
        "shell", "hpcl", "cng", "lpg", "filling station", "petrol pump",
        "service station", "fuel station", "gas station", "bunk"
    ]
    if any(keyword in d for keyword in fuel_keywords):
        return "Fuel"
    
    # 7. Education
    education_keywords = [
        "udemy", "coursera", "byju", "unacademy", "school", "college",
        "education", "course", "tuition", "books", "stationery",
        "exam", "coaching", "training", "online course", "study material",
        "khan academy", "learning", "university", "institute", "academy",
        "library", "tuition center", "coaching center"
    ]
    if any(keyword in d for keyword in education_keywords):
        return "Education"
    
    # 8. Entertainment
    entertainment_keywords = [
        "netflix", "prime video", "hotstar", "spotify", "bookmyshow",
        "sony liv", "movie", "cinema", "gaming", "ott", "streaming",
        "concert", "theatre", "play", "event", "entertainment",
        "hulu", "disney+", "gaana", "jiosaavn", "audiobook", "spotify premium",
        "youtube premium", "game", "fun", "amusement", "park", "playstation",
        "xbox", "nintendo", "casino", "betting"
    ]
    if any(keyword in d for keyword in entertainment_keywords):
        return "Entertainment"
    
    # 9. Utilities (check for specific utility patterns first)
    utilities_keywords = [
        "electricity", "power", "water", "gas", "bill", "utility",
        "internet", "wifi", "broadband", "rent", "emi", "insurance",
        "subscription", "tv subscription", "dth", "maintenance", "property",
        "housing", "society", "maintenance charge", "property tax"
    ]
    # Special check for telecom services that are not recharge
    if "airtel fiber" in d or "airtel broadband" in d or "jio fiber" in d or "jio broadband" in d:
        return "Utilities"
    if any(keyword in d for keyword in utilities_keywords):
        return "Utilities"
    
    # 10. Banking & Finance
    banking_keywords = [
        "emi", "loan", "interest", "insurance", "mutual fund", "sip",
        "credit card", "investment", "stock", "tax", "gst", "bank",
        "fd", "rd", "saving", "debit card", "net banking", "hdfc",
        "icici", "sbi", "axis bank", "upi", "finance", "wealth", "portfolio",
        "brokerage", "demat", "trading", "share", "equity", "bond"
    ]
    if any(keyword in d for keyword in banking_keywords):
        return "Banking & Finance"
    
    # 11. Recharge (now with more specific patterns)
    # Check for telecom operators ONLY with recharge indicators
    telecom_operators = ["airtel", "jio", "vi", "vodafone", "idea", "bsnl", "reliance"]
    recharge_indicators = ["recharge", "top-up", "data pack", "plan renewal", "prepaid", "postpaid", "bill payment"]
    
    # Check if it's a pure recharge transaction
    has_telecom = any(operator in d for operator in telecom_operators)
    has_recharge_indicator = any(indicator in d for indicator in recharge_indicators)
    
    if has_telecom and has_recharge_indicator:
        return "Recharge"
    
    # Also check standalone recharge keywords
    standalone_recharge = ["mobile recharge", "phone recharge", "sim recharge", "balance recharge"]
    if any(keyword in d for keyword in standalone_recharge):
        return "Recharge"
    
    # 12. Personal Care
    personal_care_keywords = [
        "salon", "spa", "gym", "barber", "beauty", "haircut",
        "skincare", "makeup", "cosmetics", "personal care", "fitness",
        "wellness center", "massage", "manicure", "pedicure", "aesthetic",
        "beauty parlor", "beauty salon", "hair salon", "nail art", "waxing"
    ]
    if any(keyword in d for keyword in personal_care_keywords):
        return "Personal Care"
    
    # 13. Home & Kitchen
    home_keywords = [
        "furniture", "home decor", "appliances", "kitchen", "utensils",
        "bed", "sofa", "curtains", "lights", "home improvement", "home",
        "interior", "decoration", "furnishing", "cookware", "crockery",
        "home center", "home depot", "home town", "home store"
    ]
    if any(keyword in d for keyword in home_keywords):
        return "Home & Kitchen"
    
    # 14. Gifts & Donations
    gifts_keywords = [
        "gift", "donation", "charity", "birthday gift", "wedding gift",
        "festival gift", "contribution", "ngo", "trust", "foundation",
        "help", "support", "fund", "donate", "present", "gift shop"
    ]
    if any(keyword in d for keyword in gifts_keywords):
        return "Gifts & Donations"
    
    # 15. Business Expenses
    business_keywords = [
        "office", "software", "tools", "stationery", "business", "consulting",
        "professional", "tax", "invoice", "meeting", "project", "client",
        "corporate", "company", "firm", "enterprise", "work", "service",
        "business card", "business lunch", "conference", "seminar", "workshop"
    ]
    if any(keyword in d for keyword in business_keywords):
        return "Business Expenses"
    
    # 16. Hobbies & Leisure
    hobbies_keywords = [
        "book", "music", "art", "craft", "game", "hobby", "sports",
        "fitness", "photography", "leisure", "instrument", "painting",
        "drawing", "reading", "writing", "gardening", "cooking", "knitting",
        "hobby store", "craft store", "music store", "book store"
    ]
    if any(keyword in d for keyword in hobbies_keywords):
        return "Hobbies & Leisure"
    
    # 17. Vehicle Maintenance
    vehicle_keywords = [
        "car service", "bike service", "vehicle repair", "oil change",
        "tyre", "garage", "vehicle", "parking", "toll", "automobile",
        "workshop", "mechanic", "service center", "auto", "motor",
        "car wash", "bike wash", "automotive", "spare parts", "accessories"
    ]
    if any(keyword in d for keyword in vehicle_keywords):
        return "Vehicle Maintenance"
    
    # 18. Child & Family
    family_keywords = [
        "school fee", "tuition", "baby", "childcare", "diaper", "toy",
        "kids", "family", "child", "play school", "activities", "kid",
        "children", "parenting", "maternity", "paternity", "nanny",
        "baby store", "kids wear", "children's store", "toys"
    ]
    if any(keyword in d for keyword in family_keywords):
        return "Child & Family"
    
    # 19. Technology & Software
    tech_keywords = [
        "software", "app subscription", "saas", "tool", "digital",
        "license", "cloud", "internet service", "technology", "app",
        "application", "platform", "system", "it", "computer", "laptop",
        "printer", "scanner", "hardware", "software store", "tech store"
    ]
    if any(keyword in d for keyword in tech_keywords):
        return "Technology & Software"
    
    # 20. Special handling for "store" keyword (AFTER all specific categories)
    # If description contains "store" but wasn't caught by any category above
    if "store" in d:
        # Check what type of store it might be
        if "medical" in d or "pharma" in d or "chemist" in d:
            return "Healthcare"
        elif "general" in d or "kirana" in d or "provision" in d:
            return "Groceries"
        elif "book" in d:
            return "Hobbies & Leisure"
        elif "gift" in d:
            return "Gifts & Donations"
        elif "toy" in d or "kids" in d or "children" in d:
            return "Child & Family"
        elif "electronic" in d or "computer" in d or "mobile" in d:
            return "Shopping"
        elif "furniture" in d or "home" in d:
            return "Home & Kitchen"
        elif "clothing" in d or "fashion" in d or "garment" in d:
            return "Shopping"
        else:
            # Default store to Shopping
            return "Shopping"
    
    # 21. Fallback for telecom operators without recharge indicators
    if has_telecom:
        # If it has telecom but no recharge indicator, check for other patterns
        if "store" in d or "center" in d or "outlet" in d or "shop" in d:
            return "Shopping"
        # Default to Recharge if no other pattern matches
        return "Recharge"
    
    # Final fallback
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
    
    date_match = re.search(r"(\d{2}\s+[A-Z]{3}\s+\d{4})", txn)
    date = None
    if date_match:
        try:
            date_str = date_match.group(1)
            date = pd.to_datetime(date_str, format="%d %b %Y")
        except Exception as e:
            print(f"Error: {e}")
    
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
        "date": date.strftime("%Y-%m-%d") if date is not None else None,
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

