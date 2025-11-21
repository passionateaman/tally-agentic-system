# main.py
from tools.company_list_tool import get_company_list
from tools.get_report_tool import get_report
from tools.summarization_tool import summarize_report
from dotenv import load_dotenv

load_dotenv()

print("\n===============================")
print("  TALLY TOOL TESTING CONSOLE")
print("===============================\n")

# -------------------------------------
# 1. Show list of companies
# -------------------------------------
print("Fetching company list...\n")

companies = get_company_list.invoke("")

if not isinstance(companies, list) or len(companies) == 0:
    print("Error: Could not retrieve company list.")
    print(companies)
    exit()

print("Available Companies:")
for idx, c in enumerate(companies, start=1):
    print(f"{idx}. {c}")

print("\n----------------------------------")
# -------------------------------------
# 2. Ask user to pick a company
# -------------------------------------
company_index = int(input("\nEnter the number of the company: "))
company_name = companies[company_index - 1]

print(f"\nSelected Company: {company_name}")

# -------------------------------------
# 3. Ask user to enter report name
# -------------------------------------
print("\nExample report names:")
print(" - Profit and Loss")
print(" - Balance Sheet")
print(" - Day Book")
print(" - Stock Summary")
print("----------------------------------")

report_name = input("\nEnter the report name EXACTLY as in Tally: ")

# -------------------------------------
# 4. Fetch report
# -------------------------------------
print(f"\nFetching '{report_name}' for company '{company_name}'...\n")

report = get_report.invoke({
    "company_name": company_name,
    "report_name": report_name
})

print("Raw Report Data (from Tally):")
print(report)

# -------------------------------------
# 5. Summarize the report
# -------------------------------------
print("\nGenerating summary...\n")

report_text = str(report)  # convert dict → text for LLM
summary = summarize_text.invoke(report_text)

print("===== SUMMARY =====")
print(summary)
print("===================\n")

print("Testing complete.\n")
