# tools/json_normalizer.py

from typing import Any, Dict, List


import re

def _safe_num(s):
    """
    Parse numeric-like strings including:
    - commas
    - currency symbols
    - Dr / Cr suffixes (Tally Balance Sheet)
    """
    if s is None:
        return None

    try:
        text = str(s).strip()

        if text == "":
            return None

        # Detect Dr / Cr
        is_cr = "cr" in text.lower()
        is_dr = "dr" in text.lower()

        # Remove non-numeric characters except dot and minus
        cleaned = re.sub(r"[^\d\.\-]", "", text.replace(",", ""))

        if cleaned in ("", ".", "-", "-."):
            return None

        val = float(cleaned)

        # Optional sign logic:
        # Convention: Dr = positive, Cr = negative
        if is_cr:
            val = -val

        return val

    except Exception:
        return None



def _safe_ratio_num(s):
    """
    For Ratio Analysis values like:
      "59,07,661.47 Dr", "17.22 : 1", "0.00 %", "0.00 days"
    Extract the first numeric chunk and parse it.
    """
    if s is None:
        return None
    text = str(s).strip()
    buf = []
    started = False
    for ch in text:
        if ch.isdigit() or ch in ",.-":
            buf.append(ch)
            started = True
        else:
            if started:
                break
            continue
    if not buf:
        return None
    cleaned = "".join(buf).replace(",", "")
    return _safe_num(cleaned)


def _extract_label_name(obj):
    """
    Try to extract a human-readable label from nested Tally dicts.

    Looks for common name keys and unwraps nested dicts if needed.
    Returns a string / number if found, else None.
    """
    if obj is None:
        return None

    if isinstance(obj, (str, int, float)):
        return obj

    if not isinstance(obj, dict):
        return None

    NAME_KEYS = ["DSPDISPNAME", "DSPACCNAME", "NAME", "LEDGERNAME", "ACCNAME"]

    for k in NAME_KEYS:
        if k in obj:
            v = obj[k]
            if isinstance(v, dict):
                return _extract_label_name(v)
            if isinstance(v, (str, int, float)):
                return v

    for v in obj.values():
        if isinstance(v, dict):
            cand = _extract_label_name(v)
            if cand is not None:
                return cand
        elif isinstance(v, (str, int, float)):
            return v

    return None


def _guess_label_and_value_from_row(row: Dict[str, Any]):
    """
    Very generic fallback:
      - pick first 'name-like' or string field as label,
      - pick first numeric-convertible field as value.
    """
    label = None
    value = None

    name_like_keys = [
        "DSPDISPNAME",
        "DSPACCNAME",
        "NAME",
        "LEDGERNAME",
        "ACCNAME",
        "STOCK",
        "ITEM",
        "RATIO",
        "PARTY",
        "GROUP",
    ]
    for k, v in row.items():
        if not isinstance(k, str):
            continue
        ku = k.upper()
        if any(h in ku for h in name_like_keys):
            if isinstance(v, (str, int, float)) and str(v).strip():
                label = str(v).strip()
                break

    if label is None:
        for k, v in row.items():
            if isinstance(v, str) and v.strip():
                label = v.strip()
                break

    for k, v in row.items():
        val = _safe_num(v)
        if val is not None:
            value = val
            break

    return label, value


def _find_block_with_keys(node: Any, required_keys: List[str]) -> Dict[str, Any] | None:
    """
    Recursively search for a dict that contains all required_keys.
    This makes the P&L handler robust even if DSPACCNAME/PLAMT are nested.
    """
    if isinstance(node, dict):
        if all(k in node for k in required_keys):
            return node
        for v in node.values():
            found = _find_block_with_keys(v, required_keys)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_block_with_keys(item, required_keys)
            if found is not None:
                return found
    return None

def normalize_day_book(envelope: dict):
    rows = []

    vouchers = envelope.get("VOUCHER", [])
    if isinstance(vouchers, dict):
        vouchers = [vouchers]

    for v in vouchers:
        particulars = v.get("PARTYLEDGERNAME")

        entries = v.get("ALLLEDGERENTRIES.LIST", [])
        if isinstance(entries, dict):
            entries = [entries]

        for e in entries:
            amt = e.get("DEBITAMOUNT") or e.get("AMOUNT")
            try:
                val = float(str(amt).replace(",", ""))
            except Exception:
                continue

            if val == 0:
                continue

            rows.append({
                "section": "Day Book",
                "label": particulars or e.get("LEDGERNAME", "Unknown"),
                "value": abs(val),
            })

    return {
        "columns": ["section", "label", "value"],
        "rows": rows,
    }
def _aggregate_parent_rows(rows):
    label_to_children = {}

    for r in rows:
        label_to_children.setdefault(r["label"].lower(), []).append(r)

    for r in rows:
        if r["value"] is not None:
            continue

        parent = r["label"].lower()
        total = 0
        found = False

        for cr in rows:
            if cr["value"] is None:
                continue

            # child rows usually contain parent name
            if parent in cr["label"].lower() and cr["label"].lower() != parent:
                total += cr["value"]
                found = True

        if found:
            r["value"] = total

    return rows



def normalize_report_tool(parsed: Any) -> Dict[str, Any]:
    """
    Normalize Tally report shapes into:

      {
        "rows": [
          {"section": "...", "label": "...", "value": number},
          ...
        ],
        "columns": ["section","label","value"]
      }

    Handles specifically:
      - Statistics (STATNAME + STATVALUE.STATDIRECT)
      - Profit & Loss (DSPACCNAME + PLAMT.PLSUBAMT/BSMAINAMT)  [robust, recursive]
      - Ratio Analysis (RATIONAME + RATIOVALUE)
      - Group Summary (DSPACCNAME + DSPACCINFO)
      - Balance Sheet (BSNAME + BSAMT.BSMAINAMT/BSSUBAMT)
      - Bills Payable / Receivable (BILLFIXED + BILLFINAL/BILLCL/BILLGSTRBALANCE/BILLOP)
    And also has a generic fallback for unknown shapes.
    """
    out = {"rows": [], "columns": ["section", "label", "value"]}

    if not isinstance(parsed, dict):
        return out

    env = parsed.get("ENVELOPE") or parsed.get("ENVELOPE".upper()) or parsed
    if not isinstance(env, dict):
        return out

    rows: List[Dict[str, Any]] = []

    # ---------- 0) STATISTICS (STATNAME + STATVALUE.STATDIRECT) ----------
    if "STATNAME" in env and "STATVALUE" in env:
        names = env.get("STATNAME")
        vals = env.get("STATVALUE")
        if isinstance(names, list) and isinstance(vals, list):
            n = min(len(names), len(vals))
            for i in range(n):
                label = names[i]
                val_obj = vals[i] or {}
                if isinstance(val_obj, dict):
                    val = _safe_num(val_obj.get("STATDIRECT"))
                else:
                    val = _safe_num(val_obj)
                rows.append(
                    {
                        "section": "Statistics",
                        "label": label,
                        "value": val,
                    }
                )
        if rows:
            out["rows"] = rows
            return out

    # ---------- 1) PROFIT & LOSS (ROBUST, NAME-ONLY DETECTION) ----------
    pl_block = _find_block_with_keys(env, ["DSPACCNAME"])
    if pl_block is not None:
        names = pl_block.get("DSPACCNAME", [])

        # possible amount containers
        amount_lists = []
        for k in ["PLAMT", "DSPACCINFO", "BSAMT"]:
            if k in pl_block and isinstance(pl_block[k], list):
                amount_lists.append(pl_block[k])

        for i, name_obj in enumerate(names):
            label = _extract_label_name(name_obj)
            if not label:
                continue

            val = None

            # try all possible amount blocks
            for amt_list in amount_lists:
                if i >= len(amt_list):
                    continue

                amt_obj = amt_list[i]
                if isinstance(amt_obj, dict):
                    for key in [
                        "PLSUBAMT",
                        "BSMAINAMT",
                        "BSSUBAMT",
                        "DSPCLAMTA",
                        "DSPOPAMTA"
                    ]:
                        if key in amt_obj:
                            val = _safe_num(amt_obj.get(key))
                            if val is not None:
                                break
                if val is not None:
                    break

            if val is None:
                continue

            rows.append({
                "section": "ProfitAndLoss",
                "label": label,
                "value": val
            })

        if rows:
            out["rows"] = rows
            return out

    # ---------- CASH FLOW PROJECTION (GENERIC COLUMN REPORT) ----------
    if "PARTICULARS" in env and isinstance(env.get("PARTICULARS"), list):
        particulars = env.get("PARTICULARS")

        # detect all column lists (periods)
        column_lists = {
            k: v for k, v in env.items()
            if isinstance(v, list)
            and len(v) == len(particulars)
            and k.upper() != "PARTICULARS"
        }

        rows = []

        for i, part in enumerate(particulars):
            label = str(part).strip()

            # start safe: only Net Balance
            if "net balance" not in label.lower():
                continue

            for col_name, col_values in column_lists.items():
                val = _safe_num(col_values[i])
                if val is None:
                    continue

                rows.append({
                    "section": "CashFlowProjection",
                    "label": col_name,   # Jan-26 / Feb-26 / Mar-26
                    "value": val
                })

        if rows:
            out["rows"] = rows
            return out

        # ---------- 4) BALANCE SHEET (BSNAME + BSAMT) ----------
    if "BSNAME" in env and "BSAMT" in env:
        names = env.get("BSNAME")
        amts = env.get("BSAMT")
        if isinstance(names, list) and isinstance(amts, list):
            n = min(len(names), len(amts))
            for i in range(n):
                name_obj = names[i] or {}
                amt_obj = amts[i] or {}

                label = _extract_label_name(name_obj)
                if label is None:
                    label = f"row_{i}"

                val = None
                if isinstance(amt_obj, dict):
                    if amt_obj.get("BSMAINAMT") not in (None, "", "null"):
                        val = _safe_num(amt_obj.get("BSMAINAMT"))
                    elif amt_obj.get("BSSUBAMT") not in (None, "", "null"):
                        val = _safe_num(amt_obj.get("BSSUBAMT"))
                    else:
                        for kk, vv in amt_obj.items():
                            vnum = _safe_num(vv)
                            if vnum is not None:
                                val = vnum
                                break
                else:
                    val = _safe_num(amt_obj)

                rows.append({
                    "section": "BalanceSheet",
                    "label": label,
                    "value": val,
                })
        if rows:
          rows = _aggregate_parent_rows(rows)
          out["rows"] = rows
          return out


    # ---------- 5) BILLS PAYABLE / RECEIVABLE (BILLFIXED + amounts) ----------
    if "BILLFIXED" in env:
        billfixed = env.get("BILLFIXED")
        billfinal = env.get("BILLFINAL")
        billcl = env.get("BILLCL")
        billgstrbal = env.get("BILLGSTRBALANCE")
        billop = env.get("BILLOP")

        if isinstance(billfixed, list):
            n = len(billfixed)

            def _get_from_list(lst, idx):
                if isinstance(lst, list) and idx < len(lst):
                    return _safe_num(lst[idx])
                return None

            for i in range(n):
                fixed = billfixed[i] or {}
                if not isinstance(fixed, dict):
                    continue

                label = fixed.get("BILLPARTY") or fixed.get("BILLREF") or fixed.get("BILLDATE")
                if not label:
                    label = f"Bill_{i}"

                val = _get_from_list(billfinal, i)
                if val is None:
                    val = _get_from_list(billcl, i)
                if val is None:
                    val = _get_from_list(billgstrbal, i)
                if val is None:
                    val = _get_from_list(billop, i)

                rows.append(
                    {
                        "section": "Bills",
                        "label": label,
                        "value": val,
                    }
                )

        if rows:
            out["rows"] = rows
            return out
        
        # ---------- STOCK SUMMARY (DSPACCNAME + DSPSTKINFO) ----------
    if "DSPACCNAME" in env and "DSPSTKINFO" in env:
        names = env.get("DSPACCNAME")
        infos = env.get("DSPSTKINFO")

        if isinstance(names, list) and isinstance(infos, list):
            n = min(len(names), len(infos))
            for i in range(n):
                name_obj = names[i] or {}
                info_obj = infos[i] or {}

                label = _extract_label_name(name_obj)
                if not label:
                    label = f"Item_{i}"

                stk = (
                    info_obj.get("DSPSTKCL", {})
                    if isinstance(info_obj, dict)
                    else {}
                )

                qty = stk.get("DSPCLQTY")
                rate = _safe_num(stk.get("DSPCLRATE"))
                amt = _safe_num(stk.get("DSPCLAMTA"))

                rows.append(
                    {
                        "section": "StockSummary",
                        "label": label,
                        "quantity": qty,
                        "rate": rate,
                        "value": amt,
                    }
                )

        if rows:
            out["rows"] = rows
            out["columns"] = ["section", "label", "quantity", "rate", "value"]
            return out
    # ---------- DAY BOOK (VOUCHER + LEDGERENTRIES.LIST) ----------
    if "VOUCHER" in env:
        vouchers = env.get("VOUCHER")
        if isinstance(vouchers, dict):
            vouchers = [vouchers]

        rows = []

        for v in vouchers:
            party = (
                v.get("PARTYLEDGERNAME")
                or v.get("LEDGERNAME")
                or "Unknown"
            )

            entries = v.get("LEDGERENTRIES.LIST", [])
            if isinstance(entries, dict):
                entries = [entries]

            for e in entries:
                amt = _safe_num(e.get("AMOUNT"))
                if amt is None or amt == 0:
                    continue

                ledger = e.get("LEDGERNAME") or party

                rows.append({
                    "section": "DayBook",
                    "label": ledger,
                    "value": abs(amt),
                    "debit": abs(amt) if amt > 0 else None,
                    "credit": abs(amt) if amt < 0 else None,
                })

        if rows:
            out["rows"] = rows
            out["columns"] = ["section", "label", "value", "debit", "credit"]
            return out

    # ---------- DAY BOOK / SALES REGISTER / CASH FLOW (COLUMN STYLE) ----------
    if (
        "DSPPERIOD" in env
        and "DSPACCINFO" in env
        and isinstance(env.get("DSPPERIOD"), list)
        and isinstance(env.get("DSPACCINFO"), list)
    ):
        periods = env["DSPPERIOD"]
        infos = env["DSPACCINFO"]

        negative_dr = 0
        positive_dr = 0

        for info in infos:
            dr = _safe_num(info.get("DSPDRAMT", {}).get("DSPDRAMTA"))
            if dr is None:
                continue
            if dr < 0:
                negative_dr += 1
            else:
                positive_dr += 1

        # 🔑 Heuristic
        is_cash_flow = negative_dr >= 2

        rows = []

        for i in range(min(len(periods), len(infos))):
            label = str(periods[i]).strip()
            info = infos[i]

            dr = _safe_num(info.get("DSPDRAMT", {}).get("DSPDRAMTA"))
            cr = _safe_num(info.get("DSPCRAMT", {}).get("DSPCRAMTA"))
            cl = _safe_num(info.get("DSPCLAMT", {}).get("DSPCLAMTA"))

            if dr is None and cr is None and cl is None:
                continue

            if is_cash_flow:
                rows.append({
                    "section": "CashFlow",
                    "label": label,
                    "inflow": cr,
                    "outflow": abs(dr) if dr is not None else None,
                    "net_flow": cl,
                })
            else:
                # 🔹 Day Book / Sales Register (same structure)
                rows.append({
                    "section": "DayBook" if positive_dr > 0 else "SalesRegister",
                    "label": label,
                    "debit": dr,
                    "credit": cr,
                    "closing_balance": cl,
                    "value": cr if cr is not None else dr,
                })

        if rows:
            out["rows"] = rows
            out["columns"] = (
                ["section", "label", "inflow", "outflow", "net_flow"]
                if is_cash_flow
                else ["section", "label", "debit", "credit", "closing_balance", "value"]
            )
            return out


    # ---------- 6) AGGRESSIVE GENERIC FALLBACK (for unknown reports) ----------

    def walk(node: Any, parent_key: str = ""):
        section_hint = "auto"
        pk = (parent_key or "").upper()
        if "RATIO" in pk:
            section_hint = "RatioAnalysis"
        elif "STOCK" in pk or "ITEM" in pk:
            section_hint = "StockSummary"

        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict):
                    label, value = _guess_label_and_value_from_row(v)
                    if label is not None and value is not None:
                        rows.append(
                            {
                                "section": section_hint,
                                "label": label,
                                "value": value,
                            }
                        )

            for k, v in node.items():
                if isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, dict):
                            label, value = _guess_label_and_value_from_row(item)
                            if label is None and value is None:
                                continue
                            if label is None:
                                label = f"{k}_{i}"
                            rows.append(
                                {
                                    "section": section_hint,
                                    "label": label,
                                    "value": value,
                                }
                            )

            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    walk(v, parent_key=k)

        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item, parent_key=parent_key)

    walk(env)

    if rows:
        out["rows"] = rows
        return out

    out["rows"] = []
    return out
