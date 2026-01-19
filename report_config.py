# report_config.py

REPORT_DEFINITIONS = """
1. **Balance Sheet**:
   - Description: A financial statement that reports a company's assets, liabilities, and shareholder equity at a specific point in time. Use this for "net worth", "total assets", "debt", or "capital" queries.

2. **Profit & Loss A/c**:
   - Description: Summarizes revenues and expenses to determine financial performance (Net Profit/Loss). Breaks down Direct/Indirect incomes and expenses. Use for "revenue", "expenses", "net profit", "cost of sales".

3. **Stock Summary**:
   - Description: A comprehensive inventory report. Displays opening/closing balances, inward/outward movements, and stock valuation. Use for "inventory count", "closing stock", "stock value", "item details".

4. **Sales Register**:
   - Description: Summary of all sales transactions (vouchers). Displays total invoice values, trends, and monthly sales performance. Use for "total sales for April", "sales trend", "transaction list".

5. **Bills Receivable**:
   - Description: Shows outstanding invoices that customers owe to the business. Use for "pending payments", "debtors list", "money incoming", "outstanding bills".

6. **Trial Balance**:
   - Description: A list of all ledger balances (Debit/Credit) to ensure mathematical accuracy. Use for "ledger balances", "summary of all accounts", "audit check".

7. **Cash/Bank Book**:
   - Description: A summary of all Cash and Bank ledgers. Shows cash-in-hand and bank balances. Use for "cash balance", "bank status", "liquidity", "money in hand".

8. **Cash Flow**:
   - Description: Tracks the inflow and outflow of cash. Use for "cash movement", "operating cash flow", "liquidity analysis".
"""

# Tally Internal Name Mapping
# Keys = User/AI Friendly Name | Values = Exact Tally XML Report Name
TALLY_XML_MAP = {
    "Balance Sheet": "Balance Sheet",
    "Profit & Loss": "ProfitAndLoss",
    "ProfitAndLoss": "ProfitAndLoss",
    "Stock Summary": "Stock Summary",
    "StockSummary": "Stock Summary",
    "Sales Register": "Sales Register",
    "SalesRegister": "Sales Register",
    "Bills Receivable": "Bills Receivable",
    "Trial Balance": "Trial Balance",
    "Cash/Bank Account": "Group Summary", # Tally quirk: often accessed via Group Summary -> Bank Accounts
    "Cash/Bank Book": "Cash/Bank Book", 
    "Cash Flow Summary": "Cash Flow",
    "Cash Flow": "Cash Flow"
}