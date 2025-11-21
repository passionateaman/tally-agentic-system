"""
Company List Tool - Fetches companies from Tally via HTTP
"""
import os
import requests
from dotenv import load_dotenv
from langchain.tools import tool
from lxml import etree

load_dotenv()
TALLY_HOST = os.getenv("TALLY_HTTP_HOST", "http://localhost:9000")

@tool
def get_company_list() -> str:
    """
    Fetch list of all companies from Tally ERP.
    Returns a formatted string with company names.
    """
    xml_request = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>List of Companies</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
            </STATICVARIABLES>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="List of Companies">
                        <TYPE>Company</TYPE>
                        <FETCH>Name</FETCH>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    
    try:
        response = requests.post(
            TALLY_HOST,
            data=xml_request.encode('utf-8'),
            headers={"Content-Type": "application/xml"},
            timeout=10
        )
        
        if response.status_code != 200:
            return f"Error: HTTP {response.status_code}"
        
        root = etree.fromstring(response.content)
        companies = []
        for company_node in root.xpath("//COMPANY"):
            name_node = company_node.find("NAME")
            if name_node is not None and name_node.text:
                companies.append(name_node.text.strip())
        
        if not companies:
            return "No companies found in Tally"
        
        # Return formatted list
        result = "Available Companies:\n"
        for i, company in enumerate(companies, 1):
            result += f"{i}. {company}\n"
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"