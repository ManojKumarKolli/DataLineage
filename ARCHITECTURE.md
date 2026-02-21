# MCPilot Lineage Investigator - Architecture Document

## EXECUTIVE SUMMARY

The **MCPilot Lineage Investigator** is an enterprise-grade data lineage and balance reconciliation platform that enables data teams to investigate data flow issues, track balance transformations across pipeline stages (RAW → STAGE → MART), and identify discrepancies in real-time.

---

## 1. SYSTEM ARCHITECTURE OVERVIEW

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE LAYER                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ MCPilot Lineage UI (React-like SPA)                      │  │
│  │ - Modern, Responsive Web Interface                       │  │
│  │ - Real-time Interactive Visualization                   │  │
│  │ - Tabbed Investigation Results                          │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬──────────────────────────────────────┘
                         │ REST API
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API LAYER (FastAPI)                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ /lineage-api/ Endpoints                                 │  │
│  │ - POST /seed (Demo Data Generation)                     │  │
│  │ - GET /reconcile (Main Investigation)                   │  │
│  │ - GET /preview (Table Previews)                         │  │
│  │ - GET /summary (Pipeline Overview)                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬──────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────┐
│  LINEAGE        │ │  NLP/LLM     │ │  DATA        │
│  SERVICE        │ │  ENGINE      │ │  SERVICE     │
└─────────────────┘ └──────────────┘ └──────────────┘
        │                  │                 │
        └──────────────┬───┴────────┬────────┘
                       ▼
         ┌─────────────────────────────┐
         │  DATA LAYER (SQLite)        │
         │  ┌───────────────────────┐  │
         │  │ Lineage Metadata DB   │  │
         │  │ - Datasets            │  │
         │  │ - Columns             │  │
         │  │ - Edges (Lineage)     │  │
         │  │ - Checks/Alerts       │  │
         │  └───────────────────────┘  │
         │  ┌───────────────────────┐  │
         │  │ Main Data DB          │  │
         │  │ - RAW Stage Tables    │  │
         │  │ - STAGE Tables        │  │
         │  │ - MART Tables         │  │
         │  └───────────────────────┘  │
         └─────────────────────────────┘
```

---

## 2. SYSTEM COMPONENTS

### 2.1 FRONTEND LAYER

**Technology Stack:**
- HTML5, CSS3, Vanilla JavaScript
- Modern UI Framework with Responsive Design
- No external framework (pure JS for lightweight deployment)

**Key Features:**
- **Investigation Form**: User inputs issue description, focus entity (account/customer), and identifier
- **Stage Overview Panel**: KPI cards showing row counts, balances, drift percentages
- **Results Dashboard**: Multi-tab interface for organized data presentation
  - Tab 1: Investigation Results (metrics, narrative, lineage path)
  - Tab 2: Queries & Results (executed SQL and result sets)
  - Tab 3: Detailed Analysis (row-level differences, CSV export)
  - Tab 4: Sample Tables (database previews with horizontal/vertical scrolling)
- **Animations & Interactions**: Smooth fade-ins, hover effects, animated lineage flow

**UI Components:**
1. Header: Logo, title, Health & Demo Data buttons
2. Sidebar: Investigation form, stage overview, sample tables
3. Main Content: Tabbed results interface
4. Tooltips & Toasts: User feedback system

---

### 2.2 API LAYER (Backend)

**Framework:** FastAPI (Python)
**Server:** Uvicorn
**Port:** 8000

**Core Endpoints:**

#### `/lineage-api/reconcile`
- **Method:** GET
- **Purpose:** Main investigation endpoint
- **Parameters:**
  - `focusBy`: "account" | "customer"
  - `identifier`: Account ID or Customer name
  - `issue`: Free-text description of problem
  - `model`: Optional LLM model override
- **Returns:**
  ```json
  {
    "metrics": { /* Summary metrics */ },
    "path": [ /* Lineage stages */ ],
    "diffs": [ /* Row-level differences */ ],
    "narrative": "AI-generated explanation",
    "queries": [ /* Generated SQL queries */ ],
    "results": [ /* Query result sets */ ]
  }
  ```

#### `/lineage-api/summary`
- **Purpose:** Fetch stage overview metrics
- **Returns:** Row counts, balances, variance percentages per stage

#### `/lineage-api/preview`
- **Purpose:** Get sample table data
- **Parameters:** `limit` (max rows per table)
- **Returns:** Table schema and sample rows

#### `/lineage-api/seed`
- **Method:** POST
- **Purpose:** Generate demo data for testing
- **Creates:** RAW, STAGE, MART tables with realistic discrepancies

#### `/lineage-api/health`
- **Purpose:** API health check
- **Returns:** Status and database connection info

---

### 2.3 LINEAGE SERVICE (Core Business Logic)

**File:** `core/lineage/lineage_router.py`

**Class:** `LineageService`

**Key Methods:**

1. **`balances_across_stages(by, key)`**
   - Queries balances for an account or customer across RAW, STAGE, MART
   - Returns: Individual rows with balances at each stage
   - Calculates: Customer-level aggregations, fees

2. **`diffs(by, key)`**
   - Compares row-level differences between RAW and STAGE
   - Returns: Side-by-side balance comparison with deltas
   - Sorted by impact (largest variance first)

3. **`narrative(payload, model_name)`**
   - Calls Capgemini LLM with investigation context
   - Generates: Human-readable explanation of discrepancies
   - Input: Metrics, diffs, semantic hints
   - Output: Executive summary narrative

4. **`seed_demo_balances()`**
   - Creates RAW, STAGE, MART tables
   - Injects realistic discrepancies (fees, adjustments)
   - Registers lineage metadata

---

### 2.4 DATA LAYER

#### Lineage Metadata Database
**File:** `data/lineage.db` (SQLite)

**Tables:**
```sql
-- Datasets registry
CREATE TABLE datasets (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  stage TEXT,              -- raw | stage | mart
  physical_table TEXT,     -- actual table name
  primary_key TEXT
);

-- Column definitions
CREATE TABLE columns (
  id INTEGER PRIMARY KEY,
  dataset_id INTEGER,
  name TEXT,
  dtype TEXT
);

-- Logical lineage edges
CREATE TABLE edges (
  id INTEGER PRIMARY KEY,
  source_id INTEGER,       -- from dataset
  target_id INTEGER,       -- to dataset
  op TEXT,                 -- CLEAN, AGG, JOIN, etc.
  expr TEXT                -- transformation expression
);

-- Quality checks & reconciliation results
CREATE TABLE checks (
  id INTEGER PRIMARY KEY,
  left_dataset_id INTEGER,
  right_dataset_id INTEGER,
  metric TEXT,             -- count, sum, avg
  left_value REAL,
  right_value REAL,
  delta REAL,
  status TEXT,             -- pass, warn, fail
  run_at TEXT
);

-- Data quality alerts
CREATE TABLE alerts (
  id INTEGER PRIMARY KEY,
  kind TEXT,               -- RECONCILE, DIFF, QUALITY
  title TEXT,
  detail TEXT,
  severity TEXT,           -- INFO, WARN, ERROR
  created_at TEXT
);
```

#### Main Data Database
**File:** Configured via `SQLITE_PATH` (default: `data/main.db`)

**Table Structure:**

```
RAW LAYER (Source systems)
├── raw_customers
│   └── (customer_id, full_name, email, phone)
├── raw_accounts
│   ├── (account_id, customer_id, account_type, balance)
├── raw_transactions
│   └── (txn_id, account_id, amount, date)
├── raw_fees
│   └── (fee_id, account_id, fee_amount, type)
└── raw_fx
    └── (fx_id, currency, rate, date)

STAGE LAYER (Cleansed, standardized)
├── stage_customers
│   └── (customer_id, full_name, email, phone)
├── stage_accounts
│   └── (account_id, customer_id, account_type, balance) [+adjustments]
├── stage_transactions
│   └── (txn_id, account_id, amount, date)
├── stage_fees
│   └── (fee_id, account_id, fee_amount, type)
└── stage_fx
    └── (fx_id, currency, rate, date)

MART LAYER (Business-ready aggregates)
├── mart_customer_balances
│   └── (customer_id, full_name, total_balance) [SUM by customer]
├── mart_txn_monthly
│   └── (customer_id, month, total_amount)
└── mart_fees_by_customer
    └── (customer_id, total_fees)
```

---

## 3. DATA FLOW & INVESTIGATION PROCESS

### Step-by-Step Investigation Flow

```
USER INPUT
    │
    ├─ Issue Description (free text)
    ├─ Focus Entity (account/customer)
    └─ Identifier (account ID or customer name)
            │
            ▼
    ┌──────────────────────┐
    │ API /reconcile Call  │
    └──────────────────────┘
            │
            ├─────────────────────────────────────────┐
            │                                         │
            ▼                                         ▼
    ┌─────────────────────┐               ┌──────────────────────┐
    │ balances_across_    │               │ diffs()              │
    │ stages()            │               │                      │
    │                     │               │ Compares RAW vs STAGE│
    │ Fetches:            │               │ - Row-by-row delta   │
    │ - RAW balance       │               │ - Variance %         │
    │ - STAGE balance     │               │ - Sorted by impact   │
    │ - MART aggregate    │               │                      │
    │ - Fees              │               │ Returns: Column data │
    │                     │               │ + row diffs          │
    │ Returns: Metrics    │               └──────────────────────┘
    │ object              │
    └─────────────────────┘
            │
            ├────────────────────────────────────┐
            │                                    │
            ▼                                    ▼
    ┌──────────────────────┐          ┌────────────────────┐
    │ Generate Queries     │          │ narrative()        │
    │                      │          │                    │
    │ SQL Strings:         │          │ LLM Prompt:        │
    │ 1. Raw vs Stage      │          │ - Metrics          │
    │ 2. Raw account details          │ - Context          │
    │ 3. Stage account     │          │ - Semantic hints   │
    │ details              │          │                    │
    │                      │          │ Output: Human-     │
    │ Returns: Query list  │          │ readable summary   │
    │                      │          └────────────────────┘
    └──────────────────────┘
            │
            └────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Construct Response JSON    │
        ├────────────────────────────┤
        │ metrics: {...}             │
        │ path: [raw, stage, mart]   │
        │ diffs: [[...], [...]]      │
        │ narrative: "..."           │
        │ queries: [...]             │
        │ results: [...]             │
        └────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Frontend Receives JSON     │
        │ & Renders Tabs:            │
        │ 1. Investigation Results   │
        │ 2. Queries & Results       │
        │ 3. Detailed Analysis       │
        │ 4. Sample Tables           │
        └────────────────────────────┘
```

---

## 4. LINEAGE VISUALIZATION

### Three-Stage Lineage Path

```
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│   RAW STAGE      │   →    │  STAGE STAGE     │   →    │  MART STAGE      │
│                  │        │                  │        │                  │
│ Account Balance: │        │ Account Balance: │        │ Customer Balance:│
│ $15,000.00       │        │ $15,050.00       │        │ $19,250.50       │
│                  │        │                  │        │                  │
│ Row Count: 1     │        │ Row Count: 1     │        │ Aggregated       │
│                  │        │ (cleansed)       │        │ (2 accounts)     │
└──────────────────┘        └──────────────────┘        └──────────────────┘
         │                          │                          │
         │                          ▼                          │
         │                  Delta: +$50 (+0.33%)              │
         │                                                     ▼
         │                                            Delta: +$4,200.50
         │                                            (from other account)
         │
         └─── Quality Issues: ───────────────────────┘
              - Fees ($50) applied at stage level
              - Possible adjustments or reconciliations
```

### Entities in Lineage

**Account-Level Lineage:**
- Source: raw_accounts (per-account balance)
- Transform: CLEAN (data validation, type casting)
- Stage: stage_accounts (cleansed balance)
- Transform: JOIN with fees
- Target: mart_customer_balances (aggregated to customer)

**Customer-Level Lineage:**
- Source: raw_customers, raw_accounts
- Transform: AGGREGATE (SUM balances by customer)
- Stage: stage_customers, stage_accounts
- Target: mart_customer_balances

---

## 5. TECHNOLOGY STACK

### Backend
| Layer | Technology | Purpose |
|-------|-----------|---------|
| API Framework | FastAPI | RESTful endpoints |
| Server | Uvicorn | ASGI app server |
| Language | Python 3.11+ | Core logic |
| Database | SQLite | Metadata & data storage |
| LLM | Capgemini (Claude 3.5 Sonnet) | Natural language narratives |
| Config | Environment Variables | Dynamic configuration |

### Frontend
| Component | Technology |
|-----------|-----------|
| Markup | HTML5 |
| Styling | CSS3 |
| Logic | Vanilla JavaScript |
| Syntax Highlight | Highlight.js |
| Icons | Unicode/CSS |

### DevOps
| Tool | Use |
|------|-----|
| Git | Version control |
| Virtual Env | Python dependency isolation |
| CORS | Cross-origin requests |
| Static Files | UI asset serving |

---

## 6. KEY FEATURES & CAPABILITIES

### Feature Matrix

| Feature | Description | Status |
|---------|-------------|--------|
| **Account-Level Investigation** | Drill into specific account balances | ✓ Implemented |
| **Customer-Level Investigation** | Aggregate view across all customer accounts | ✓ Implemented |
| **Balance Reconciliation** | Compare RAW vs STAGE vs MART | ✓ Implemented |
| **Variance Tracking** | Calculate deltas and percentages | ✓ Implemented |
| **AI Narratives** | LLM-generated explanations | ✓ Implemented |
| **Query Transparency** | Show actual SQL queries executed | ✓ Implemented |
| **Query Results** | Display result sets in formatted tables | ✓ Implemented |
| **Row-Level Diffs** | Side-by-side comparison of discrepancies | ✓ Implemented |
| **Data Preview** | Sample tables from each stage | ✓ Implemented |
| **CSV Export** | Export diffs to CSV format | ✓ Implemented |
| **Responsive UI** | Mobile, tablet, desktop support | ✓ Implemented |
| **Smooth Animations** | Card effects, lineage flow, row animations | ✓ Implemented |
| **Multi-Tab Interface** | Organized result presentation | ✓ Implemented |
| **Real-Time Health Check** | API status verification | ✓ Implemented |
| **Demo Data Seeding** | Generate test/sample data | ✓ Implemented |

---

## 7. REQUEST-RESPONSE CYCLE

### Example Investigation Request

```http
GET /lineage-api/reconcile?focusBy=account&identifier=102&issue=Balance%20mismatch
```

### Response Structure

```json
{
  "metrics": {
    "raw_balance": 15000.00,
    "stage_balance": 15050.00,
    "mart_customer_total": 19250.50,
    "fees_total": 50.00,
    "delta_stage_vs_raw": 50.00,
    "delta_stage_vs_raw_pct": 0.0033
  },
  "path": [
    {
      "stage": "raw",
      "label": "Raw account snapshot",
      "balance": 15000.00,
      "delta_balance": null,
      "delta_percent": null
    },
    {
      "stage": "stage",
      "label": "Staging account snapshot",
      "balance": 15050.00,
      "delta_balance": 50.00,
      "delta_percent": 0.0033
    },
    {
      "stage": "mart",
      "label": "Customer-level mart total",
      "balance": 19250.50,
      "delta_balance": 4200.50,
      "delta_percent": 0.2791
    }
  ],
  "diffs": [
    [102, 15000, 15050, 50]
  ],
  "narrative": "The mart balance of $19,250.50 correctly represents the sum of this customer's accounts...",
  "queries": [
    {
      "type": "SQL",
      "query": "SELECT r.account_id, r.balance AS raw_balance, s.balance AS stage_balance, ... FROM raw_accounts r LEFT JOIN stage_accounts s ..."
    }
  ],
  "results": [
    {
      "name": "Raw vs Stage Balance for Account",
      "columns": ["account_id", "raw_balance", "stage_balance", "delta"],
      "rows": [[102, 15000, 15050, 50]]
    }
  ]
}
```

---

## 8. SYSTEM SCALABILITY & EXTENSIBILITY

### Current Scope
- Single SQLite database (suitable for millions of rows)
- Synchronous request processing
- In-memory query generation

### Scalability Options
1. **Database**: Migrate to PostgreSQL or cloud data warehouse (BigQuery, Snowflake)
2. **API**: Add async/await with ASGI for concurrent requests
3. **Caching**: Redis for frequently accessed lineage metadata
4. **Batch Processing**: Background jobs for alert generation and validation
5. **UI**: Server-side rendering or framework migration (Next.js, Vue)

### Extensibility Points
- **Custom Metrics**: Plugin system for domain-specific KPIs
- **Additional Stages**: Support for more ETL pipeline stages
- **Alerting**: Webhook integration for incident management
- **Audit Trail**: Database versioning and change history
- **Multi-Tenant**: Namespace separation for enterprise deployments

---

## 9. SECURITY & COMPLIANCE

### Current Implementation
- CORS middleware for cross-origin requests
- Environment-based configuration (no hardcoded secrets)
- Read-only queries for data investigation
- Error handling without sensitive data exposure

### Recommended Enhancements
- API authentication (JWT or OAuth2)
- Role-based access control (RBAC)
- Audit logging of investigations
- Data encryption at rest and in transit
- SQL injection prevention (parameterized queries)

---

## 10. DEPLOYMENT ARCHITECTURE

### Current Setup
```
Development:
├── Local Uvicorn server (port 8000)
├── SQLite databases in /data/
└── Static UI files in /ui/lineage/

Production (Recommended):
├── Docker container
├── Kubernetes orchestration (optional)
├── PostgreSQL backend
├── Cloud storage for UI assets (S3/GCS)
└── Load balancer (ALB/Nginx)
```

### Docker Deployment
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "apps.graphrag_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 11. KEY DIFFERENTIATORS

1. **End-to-End Transparency**: Users see actual queries executed and results returned
2. **AI-Powered Narratives**: LLM provides human-readable explanations of data issues
3. **Interactive Visualization**: Animated lineage flow showing data transformation stages
4. **Multi-Stage Reconciliation**: Automatic comparison across RAW, STAGE, MART layers
5. **Real-Time Investigation**: Sub-second response times for most queries
6. **No Code Required**: Non-technical users can investigate data issues
7. **Extensible Design**: Plugin architecture for custom metrics and stages

---

## CONCLUSION

The MCPilot Lineage Investigator provides a unified platform for data teams to:
- ✅ Understand data flow across pipeline stages
- ✅ Identify and investigate discrepancies
- ✅ Generate audit trails for compliance
- ✅ Make data-driven decisions with confidence

By combining SQL-based reconciliation, AI-powered narratives, and an intuitive UI, it bridges the gap between technical data engineers and business stakeholders.

---

## APPENDIX: GLOSSARY

| Term | Definition |
|------|-----------|
| **RAW** | Source data directly from systems (unmodified) |
| **STAGE** | Cleansed, standardized data ready for analysis |
| **MART** | Business-ready aggregated data for reporting |
| **Lineage** | Path of data transformation from source to destination |
| **Delta** | Numerical difference between two values |
| **Reconciliation** | Process of matching/comparing data across systems |
| **Metadata** | Data describing data structure and relationships |
| **Narrative** | Human-readable explanation generated by LLM |
| **Metrics** | Key performance indicators (counts, sums, percentages) |
| **Drift** | Unexpected change in data values or patterns |
