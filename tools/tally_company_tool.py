# tools/tally_company_tool.py
import pyodbc
from langchain.tools import tool
from dotenv import load_dotenv
import os

# Load the .env variables
load_dotenv()

CONNECTION_STRING = os.getenv("ODBC_CONNECTION_STRING")


@tool("get_company_list")
def get_company_list() -> list:
    """
    Fetch list of companies from Tally using ODBC (DSN-less).
    Uses connection string from .env.
    """

    if not CONNECTION_STRING:
        return {"error": "ODBC_CONNECTION_STRING not found in .env"}

    try:
        conn = pyodbc.connect(CONNECTION_STRING, autocommit=True)
        cursor = conn.cursor()
    except Exception as e:
        return {"error": f"ODBC connection failed: {str(e)}"}

    try:
        cursor.execute("SELECT $Name FROM Company")
        companies = [row[0] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return companies

    except Exception as e:
        return {"error": f"ODBC query failed: {str(e)}"}