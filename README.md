# Backend setup

```powershell
cd "C:\Users\mhuza\OneDrive\Desktop\Data Scraping"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
playwright install chromium
uvicorn backend.main:app --reload --port 8000
```

Configure the single `backend/.env` file before starting the API:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-service-role-key
BACKEND_DATA_DIR=data
```

Start `npm run dev` in another terminal and use Create Scraping Session. No saved Adapt URL is needed: the exporter opens Adapt's base search page and applies the selected filters in the visible browser. The app login credentials are passed only to the visible Adapt login form when the saved Adapt session has expired; they are deleted immediately and are never written to the database. Supabase stores jobs and pipeline metadata; the mounted `backend/data/` directory stores job-specific browser state and CSV artifacts.

When a run finishes, download **Master CSV** for the cleaned ten-column dataset and **Email Candidates** for the eight MailTester-ready email formats. The original visible Adapt export remains available as the raw CSV for audit purposes.

## MailTester Ninja to Salesforce

1. Download **Email Candidates** and upload it to MailTester Ninja.
2. Upload MailTester's verified CSV with **Upload Verified CSV** on the completed session.
3. The backend keeps only accepted/valid/verified/deliverable addresses, matches each address to the original candidate row, removes duplicates (LinkedIn URL first, then email), and creates **Salesforce CSV**.

The Salesforce CSV contains: `First Name`, `Last Name`, `Title`, `Company`, `LinkedIn URL`, `Domain`, `Industry`, `Email`, `Headcount`, and `Location`.

If Adapt changes its filter DOM, update the selectors in `backend/utils/exporter/config.py`. Exporter settings such as `HEADLESS` and `TIMEOUT_MS` also belong in this same `backend/.env` file.
