"""Short-description templates. {sub} = subcategory label, {site} = caller's site."""
from __future__ import annotations

TEMPLATES: dict[str, list[str]] = {
    "inquiry": ["Question about {sub}", "How do I use {sub}?", "Request for help with {sub}",
                "{sub}: need guidance"],
    "software": ["{sub} not responding", "Error message in {sub}", "{sub} very slow since this morning",
                 "Cannot log in to {sub}", "{sub} crashes when saving"],
    "hardware": ["{sub} not working", "{sub} failure on workstation", "Replace faulty {sub}",
                 "{sub} issue on shop-floor PC in {site}"],
    "network": ["{sub} problem in {site}", "Intermittent {sub} connectivity", "No {sub} on production line in {site}",
                "{sub} down for several users"],
    "database": ["{sub} performance degraded", "{sub} connection errors", "{sub} job failed overnight"],
    "password_reset": ["Password reset request", "Account locked out", "Forgot password, cannot log in"],
    "pc_issue": ["PC issue", "Computer problem"],          # legacy category (D6)
    "": ["Issue reported by user", "User needs assistance"],  # missing category (D6)
}

ERP_WAVE_TEMPLATES = ["SAP transaction fails after weekend upgrade", "Cannot post goods receipt in SAP",
                      "ERP order entry error since Monday", "SAP MRP run incomplete", "Invoice posting blocked in ERP"]

SUBCATEGORY_LABELS = {
    "oracle": "Oracle", "sql server": "MS SQL Server", "db2": "DB2", "cpu": "CPU", "keyboard": "Keyboard",
    "memory": "Memory", "mouse": "Mouse", "disk": "Disk", "monitor": "Monitor", "email": "Email",
    "internal application": "Internal application", "antivirus": "Antivirus", "dhcp": "DHCP",
    "ip address": "IP address", "dns": "DNS", "vpn": "VPN", "wireless": "Wi-Fi", "os": "Windows",
    "erp": "SAP", "mes": "MES", "": "system",
}

CLOSE_NOTES: dict[str, list[str]] = {
    "Solution provided": ["Issue fixed and confirmed with the user.", "Configuration corrected; user confirmed service restored."],
    "Workaround provided": ["Workaround applied; permanent fix tracked separately.", "Temporary workaround given to the user."],
    "Resolved by caller": ["User reports the issue resolved itself.", "Caller resolved the issue before intervention."],
    "User error": ["Incorrect usage; user guided through the correct steps."],
    "Known error": ["Matches a known error; documented workaround applied."],
    "Resolved by change": ["Resolved by the implementation of a change."],
    "Resolved by problem": ["Root cause fixed through problem management."],
    "Resolved by request": ["Fulfilled through a service request."],
    "Duplicate": ["Duplicate of an existing incident."],
    "No resolution provided": ["Closed without resolution details."],
}
