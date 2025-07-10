The Credit App

is built on a real-time database architecture and consists of four core components:

⸻

	1.	Input Data (Requestor Form Extraction)
 • This module captures data from a requestor-facing form, where users submit credit-related information.
 • It extracts and structures form submissions into standardized records.
 • Each request is automatically logged and assigned a unique ticket ID for tracking.

⸻

	2.	Internal Ticketing System (Status Updates)
 • The internal system allows designated users to update the status of submitted credit requests.
 • Facilities and staff can log outcomes such as approvals, denials, or additional documentation needs.
 • This ensures all records remain synchronized in real time across the platform.

⸻

	3.	Lookup Function (User Status Check)
 • Any user—internal or external—can access the lookup tool to check the current status of a credit request.
 • By entering the unique ticket ID, users can view real-time updates, ensuring full transparency and reducing manual follow-ups.

⸻

	4.	Bulk Request Conversion Tool
 • This utility allows users to upload external files (e.g., Excel-based credit logs) and convert them into fully structured requestor entries.
 • It supports column validation, data cleansing, and duplicate prevention by matching invoice and item numbers.
 • All valid records are automatically submitted to Firebase with standardized fields and a ticket trail for internal tracking.

⸻

