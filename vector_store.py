# vector_store.py
import chromadb
from chromadb.utils import embedding_functions

# Initialize Local Vector DB
CHROMA_CLIENT = chromadb.PersistentClient(path="./tally_chroma_db")

# Use a free, lightweight embedding model (runs locally, no API cost)
EMBED_FN = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

COLLECTION_NAME = "tally_reports"

def setup_vector_db():
    """
    Populates the database with Tally Report descriptions.
    Run this ONCE or whenever you add new reports.
    """
    # Delete old collection if exists to ensure fresh start
    try: CHROMA_CLIENT.delete_collection(COLLECTION_NAME)
    except: pass

    collection = CHROMA_CLIENT.create_collection(name=COLLECTION_NAME, embedding_function=EMBED_FN)

    # --- THE KNOWLEDGE BASE ---
    # We map semantic descriptions to the EXACT internal Tally name.
    reports = [
        {
            "id": "bs_01",
            "tally_name": "Balance Sheet", 
            "desc": "Balance Sheet. Financial statement of assets, liabilities, and equity. Shows net worth, debt, capital, and loans."
        },
        {
            "id": "pl_01",
            "tally_name": "ProfitAndLoss",
            "desc": "ProfitAndLoss. P&L. Income statement. Shows revenue, sales, expenses, net profit, cost of sales, and gross profit."
        },
        {
            "id": "stk_01",
            "tally_name": "Stock Summary",
            "desc": "Stock Summary. Inventory report. Shows closing stock, item quantities, stock value, inward outward goods, and stock valuation."
        },
        {
            "id": "sale_01",
            "tally_name": "Sales Register",
            "desc": "Sales Register. List of all sales invoices and transactions. Shows monthly sales performance and trends."
        },
        {
            "id": "tb_01",
            "tally_name": "Trial Balance",
            "desc": "Trial Balance. List of all ledger account balances (debit and credit). Used for audit and checking accounting accuracy."
        },
        {
            "id": "br_01",
            "tally_name": "Bills Receivable",
            "desc": "Bills Receivable. Outstanding bills. Money owed to the business by customers (debtors). Pending payments."
        },
        {
            "id": "bank_01",
            "tally_name": "Cash Flow",
            "desc": "Cash and Bank Book. Group Summary for Bank Accounts. Shows cash in hand, bank balance, and liquidity."
        }
    ]

    collection.add(
        documents=[r["desc"] for r in reports],
        metadatas=[{"tally_name": r["tally_name"]} for r in reports],
        ids=[r["id"] for r in reports]
    )
    print("Vector Database populated with Tally Reports!")

def get_best_report(query: str):
    """
    Queries the vector DB to find the single best matching report.
    Returns the EXACT Tally XML name.
    """
    collection = CHROMA_CLIENT.get_or_create_collection(name=COLLECTION_NAME, embedding_function=EMBED_FN)
    
    results = collection.query(
        query_texts=[query],
        n_results=1
    )
    
    if results['metadatas'] and results['metadatas'][0]:
        best_match = results['metadatas'][0][0]
        print(f"🔍 Vector Search: Query='{query}' -> Match='{best_match['tally_name']}'")
        return best_match['tally_name']
    
    return "Balance Sheet" # Default fallback

if __name__ == "__main__":
    setup_vector_db()