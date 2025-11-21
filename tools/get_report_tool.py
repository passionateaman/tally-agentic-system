"""
Get Report Tool - Fetches specific reports from Tally via HTTP
"""
import os
import requests
import json
from dotenv import load_dotenv
from langchain.tools import tool
from lxml import etree

load_dotenv()
TALLY_HOST = os.getenv("TALLY_HTTP_HOST", "http://localhost:9000")

REPORT_MAPPING = {
    "balance sheet": "Balance Sheet",
    "balancesheet": "Balance Sheet",
    "bs": "Balance Sheet",
    "profit and loss": "Profit and Loss",
    "p&l": "Profit and Loss",
    "pl": "Profit and Loss",
    "day book": "Day Book",
    "stock summary": "Stock Summary",
}

@tool
def get_report(company_name: str, report_name: str) -> str:
    """
    Fetch a specific report from Tally ERP.
    
    Args:
        company_name: Exact name of the company
        report_name: Name of report (Balance Sheet, Profit and Loss, Day Book, Stock Summary)
    
    Returns:
        JSON string with report data
    """
    normalized_report = REPORT_MAPPING.get(report_name.lower(), report_name)
    
    xml_request = f"""<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>{normalized_report}</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                <SVCURRENTCOMPANY>{company_name}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
    </BODY>
</ENVELOPE>"""
    
    try:
        response = requests.post(
            TALLY_HOST,
            data=xml_request.encode('utf-8'),
            headers={"Content-Type": "application/xml"},
            timeout=15
        )
        
        if response.status_code != 200:
            return json.dumps({"error": f"HTTP {response.status_code}"})
        
        root = etree.fromstring(response.content)
        
        # Extract data
        report_data = {
            "company": company_name,
            "report_type": normalized_report,
            "data": extract_report_data(root, normalized_report)
        }
        
        return json.dumps(report_data, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})

def extract_report_data(root, report_type):
    """Extract key data from XML based on report type"""
    items = []
    for node in root.xpath("//DSCALCFIELD | //DSP*"):
        name_node = node.find(".//DSPDISPNAME")
        amount_node = node.find(".//DSCALCULATEDAMT")
        
        if name_node is not None and amount_node is not None:
            items.append({
                "name": name_node.text if name_node.text else "",
                "amount": amount_node.text if amount_node.text else "0"
            })
    
    return items if items else [{"info": "Report data available in XML"}]
