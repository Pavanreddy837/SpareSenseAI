# SpareSenseAI
### AI-Assisted Spare Parts Inventory Decision Support Dashboard

SpareSenseAI is an inventory decision-support project that helps identify potential spare-parts shortages and evaluate replenishment options using inventory, sales, purchase-order, product, and supplier data.

## Problem Statement

Businesses managing spare parts across multiple locations can face unexpected stockouts, excess inventory, supplier lead-time challenges, and time-consuming manual analysis. SpareSenseAI brings relevant inventory information together to help users identify potential risks and make more informed replenishment decisions.

## Objectives

- Improve visibility into inventory across locations.
- Estimate daily demand from available sales history.
- Identify potential stock shortage risks.
- Evaluate possible stock transfers and supplier options.
- Support human-reviewed replenishment decisions.
- Maintain a history of saved decisions.

## Key Features

- Inventory dashboard and stock overview.
- Sales-based demand and stock-cover analysis.
- Potential shortage-risk identification.
- Supplier comparison using lead time, estimated price, and minimum order quantity.
- Transfer and purchase-order recommendations.
- Human approval workflow and decision-history tracking.

## Technology Stack

- **Backend:** Python, FastAPI
- **Frontend:** HTML, CSS, JavaScript
- **Data sources:** CSV files for inventory, sales, products, suppliers, and purchase orders

## How It Works

1. Load the available inventory and related CSV data.
2. Analyze sales history to estimate daily demand.
3. Calculate estimated stock cover and compare it with supplier lead times.
4. Consider relevant purchase orders and possible stock transfers.
5. Evaluate supplier options when replenishment is needed.
6. Present recommended actions for human review.

## Run Locally

1. Install Python and ensure it is available in your terminal.
2. Clone this repository:

   ```bash
   git clone https://github.com/Pavanreddy837/SpareSenseAI.git
   cd SpareSenseAI
   ```

3. Create and activate a virtual environment.

   **Windows PowerShell:**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies using the project's dependency file, if provided:

   ```powershell
   pip install -r requirements.txt
   ```

5. Start the application from the project root:

   ```powershell
   python -m uvicorn backend.main:app --reload --port 8001
   ```

6. Open the dashboard at http://127.0.0.1:8001/.

   If dependencies are not listed in `requirements.txt`, install the project's actual required packages before starting the application.

## Decision and Approval Notes

SpareSenseAI currently uses data-driven analysis and rule-based recommendations. It should not be interpreted as a verified trained machine-learning forecasting system.

Purchase-order recommendations remain pending human approval. The demo approval and history workflows do not submit real supplier orders, write to an external ERP system, or physically move stock.

## Limitations and Future Improvements

- Validate the quality and date range of incoming data.
- Improve demand forecasting and evaluate it against historical outcomes.
- Integrate with ERP and supplier systems in a future version.
- Add operational alerts, access controls, and further audit capabilities.

## Project Status

Prototype for inventory decision support and demonstration. Recommendations should be reviewed by a responsible person before real-world action.
