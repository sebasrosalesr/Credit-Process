🧾 The Credit App — Real-Time Automation & Analysis Platform
The Credit App is built on a real-time database architecture powered by Firebase and Python automation. It integrates multiple data processing pipelines, interactive dashboards, and PDF-to-record analysis tools that connect requestors, internal teams, and billing validation workflows.

⚙️ 1. Input Data — Requestor Form Extraction
	•	Captures submissions from a user-facing credit request form. 
	•	Extracts, validates, and structures raw entries into standardized database records. 
	•	Automatically assigns a unique ticket ID for full lifecycle tracking. 
	•	Supports CSV / Excel intake and API-based form ingestion.

🧭 2. Internal Ticketing System — Real-Time Status Management
	•	Enables internal users to update credit request statuses (Approved, Denied, Pending, TBD). 
	•	Tracks all outcomes and actions in real time through Firebase. 
	•	Synchronizes updates instantly across the Requestor, Analyst, and Management dashboards. 
	•	Maintains historical audit trails for compliance and reporting.

🔍 3. Lookup Function — User Status Check Portal
	•	Allows internal and external users to check live ticket statuses. 
	•	Provides transparent updates on credit resolution progress by Ticket ID. 
	•	Reduces manual follow-ups through automatic, read-only visibility. 
	•	Integrates optional PDF parsing and case file matching to display supporting documentation directly in the lookup view.

📦 4. Bulk Request Conversion Tool — Structured Batch Upload
	•	Converts raw or external files (Excel, CSV logs) into standardized Firebase entries. 
	•	Includes intelligent column mapping, validation, and data cleansing. 
	•	Detects and prevents duplicates using invoice + item-pair matching logic. 
	•	Automatically appends metadata, timestamps, and assigned ticket identifiers.

📊 5. Analysis & Intelligence Tools — Operational Insights
	•	Contains multiple analytical utilities for monitoring and improving credit operations:
	•	Credit Notes Analyzer – extracts “Background” notes from PDF case files and matches them to Firebase tickets by Case / Invoice / Item.
	•	Resolution Time Tracker – measures turnaround times (median / mean) by agent, department, and month.
	•	Root Cause Classification – leverages machine-learning models for text-based issue labeling.
	•	Anomaly Detection Dashboard – flags unusual credit trends or high-frequency items.
	•	Workload Forecasting – daily ticket-volume predictions using Prophet time-series modeling.

📗 6. Workbook Comparison & Automation Suite
	•	Three-Workbook Comparison Tool – aligns and reconciles three Excel workbooks:
	•	Pricing or Credit Request File 
	•	SOP / Reference Rules 
	•	Billing Master Automatically highlights discrepancies and merges unified results.
	•	Billing Master Auto-Update – refreshes margin, cost, and category data from validated source files.
	•	Supports fuzzy matching and incremental syncs to maintain a clean, up-to-date pricing master.

💡 Tech Stack
	•	Frontend: Streamlit (interactive dashboards & upload tools) 
	•	Backend: Python (pandas, pdfplumber, scikit-learn, Prophet) 
	•	Database: Firebase RTDB (real-time synchronization) 
	•	Integrations: Google Drive / Colab / AWS Lambda (for scalable automation)

