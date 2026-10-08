Part 1 

PantryPulse: AI Food Allocation for a Regional Food Bank (Non-profit)

Company context and current challenges

Harvest Bridge Food Bank (a hypothetical regional non-profit) collects donated food from grocery chains, farms, and food drives. It distributes it to 85 partner pantries across six counties, serving about 40,000 households a month. Allocation is handled by three coordinators using spreadsheets, phone calls, and memory. Donations arrive unpredictably, often as emailed manifests or photos of pallets, and nearly half are perishable with only 3–7 days of shelf life.

Specific business problem

Food is not reaching the pantries that need it before it spoils. Harvest Bridge discards roughly 12% of perishable donations, while 1 in 4 pantries reports running out of protein or fresh produce before the end of each distribution week. Each spoiled pallet means meals that never reached families and a donor relationship put at risk. Coordinators spend about 12 hours a week manually re-typing manifests and deciding who gets what, so allocation decisions are slow and inconsistent.

Target users and needs

Warehouse coordinators need instant, structured intake of donations and recommended allocations they can approve or adjust.
Pantry managers need to know what is arriving and when, and a simple way to report shortages.
The operations director needs visibility into waste, unmet demand, and trends for grant reports and donor outreach.
Why AI is the right solution

Demand at each pantry follows patterns a person cannot track across 85 sites: seasonality, school holidays, benefit-payment cycles, and weather. Time-series forecasting can learn these patterns from three years of distribution history. Donation intake is unstructured (emails, PDFs, photos), and a large language model can convert it into clean inventory records. A rules-only system could handle neither the variability in demand nor the messiness of the inputs.

Success metrics

Reduce perishable spoilage from 12% to under 8% within six months
Reduce pantry stockouts by 30%
Cut the coordinator's manual allocation time from 12 to 4 hours per week
Weighted forecast error (WAPE) under 20% per pantry and category
Coordinators accept at least 70% of AI allocation recommendations without major edits
MVP features

AI donation intake: upload an email, PDF, or photo, and the LLM extracts items, quantities, and expiry dates for coordinator review
Weekly demand forecast per pantry and food category
Expiry-aware allocation recommendations with one-click approval
Pantry portal showing incoming deliveries and a shortage report form
Waste and impact dashboard
(About 360 words, not counting the title.)

Part 2 post

PantryPulse: Technical Plan

How I used AI to develop this

I asked Claude for five AI full-stack use cases across industries:

Hospital pharmacy stock forecasting (healthcare)
An adaptive quiz tutor (education)
Return-risk prediction at checkout (e-commerce)
Invoice anomaly detection for small businesses (finance)
Predictive maintenance from machine sensor data (manufacturing)
The pharmacy idea inspired me to apply forecasting-plus-inventory logic to a non-profit, where waste directly means missed meals. It also builds on my earlier time-series forecasting project. I then had Claude expand the idea into the architecture, features, coding-agent plan, and App Runner strategy below.

Application description

PantryPulse is a full-stack web app with three roles: coordinator, pantry manager, and admin. The data flows like this:

Users on a browser or phone reach a web service (Next.js on App Runner).
The web service calls an API service (FastAPI on App Runner).
The API service connects to RDS PostgreSQL, Amazon Bedrock, and S3.
A weekly-scheduled job triggers model retraining and an allocation refresh via a protected API endpoint.
Technology stack with justification

Layer	Choice	Why
Frontend	Next.js (React + TypeScript), Tailwind CSS, Recharts	Role-based dashboards and forms. Mobile-friendly pages for volunteers on phones. TypeScript catches errors in AI-generated code.
Backend	FastAPI (Python)	Same language as the forecasting stack (pandas, LightGBM). Handles async calls to Bedrock. Auto-generates OpenAPI docs, which produce a typed frontend client.
Database	Amazon RDS for PostgreSQL + SQLAlchemy/Alembic	Relational data with strict integrity (donations → items → allocations → pantries). JSONB columns store raw LLM output for auditing.
Generative AI	Amazon Bedrock (Claude)	Reads images, PDFs, and text through one API. Supports tool calling. Authenticates with IAM roles, so no API keys sit in the container.
Predictive ML	LightGBM global model, compared against a seasonal-naive baseline	One model covers 85 pantries × 8 categories using calendar, holiday, benefit-cycle, and weather features. Trains in seconds.
Optimization	Google OR-Tools linear program	Assigns inbound stock to meet the most forecast demand while penalizing expiry risk and travel distance.
Auth	Amazon Cognito (user groups)	Provides role-based access without building auth from scratch.
Storage & jobs	S3; EventBridge Scheduler + small Lambda	S3 holds uploads and model files. The scheduler triggers weekly retraining and daily allocation refreshes.
Hosting	AWS App Runner (2 services)	Auto-scaling containers with HTTPS by default and no servers to manage. Right-sized for a small non-profit team.
Key features and how they solve the problem

AI donation intake. A coordinator uploads a photo, PDF, or forwarded email. Bedrock returns structured JSON (item, category, quantity, unit, expiry date, storage type), which is validated against a Pydantic schema. Low-confidence fields are highlighted for review.
SolBedrock hours a week of manual re-typing.
Demand forecasting. The model produces a weekly forecast per pantry and category, with prediction intervals. Inputs include lagged demand, week of the year, school holidays, benefit issuance dates, and weather. Past distributions were capped by supply, so they under-record true demand (censored demand). Shortage reports and household visit counts are used to correct for this.
Solves: stockouts caused by guesswork.
Expiry-aware allocation. The optimizer proposes which pantry items go where, prioritizing those closest to expiry. The LLM adds a one-line plain-English reason for each recommendation, for example: "Pantry 14: forecast short 300 lb dairy, 6 miles away." Coordinators approve, edit, or reject each one, and their edits are logged to tune the optimizer.
Solves: spoilage and inconsistent decisions.
Pantry portal. A mobile-friendly view of incoming deliveries, plus a 30-second shortage report that feeds back into the forecast.
Solves: pantries being left out of the loop.
Impact dashboard. Tracks spoilage percentage, stockouts, pounds distributed, and households served. It also produces an AI-drafted monthly summary for grant reports.
Solves: manual reporting for donors.
"Ask PantryPulse" assistant (Phase 2, after the MVP). Coordinators ask questions like "Which pantries will be short on protein next week?" The LLM answers only by calling a fixed set of read-only query functions, never free-form SQL, so it cannot modify or expose data.
AI coding agents I will use

Claude Code for backend and infrastructure. It will scaffold FastAPI routes, SQLAlchemy models, Alembic migrations, pytest suites, Dockerfiles, and the GitHub Actions pipeline. A CLAUDE.md file will hold the schema, naming conventions, and a "write tests first" rule to keep the generated code consistent across sessions.
Cursor for the frontend. It will build React components, forms, and charts against the typed API client generated from FastAPI's OpenAPI spec, so the frontend and backend cannot drift apart.
My guardrails:
I will give the agents small, scoped tasks.
Tests get written before the code they check.
I review every diff before merging.
I own the forecasting backtests myself, since that is where subtle bugs like data leakage hide.
Build plan

Week 1: schema, auth, and skeletons of both services deployed to App Runner
Week 2: donation intake, the review screen, and evaluation against a golden test set
Week 3: forecasting pipeline, backtesting, and the allocation optimizer
Week 4: pantry portal, dashboard, load testing, and polish
AWS App Runner deployment strategy

Two services (web and api), each built from a Docker image stored in Amazon ECR.
GitHub Actions runs on every push to main: runs tests, builds the image, pushes it to ECR, and App Runner auto-deploys. Staging and production are separate services.
A VPC connector lets the API reach RDS in private subnets. Database credentials are injected from Secrets Manager as environment variables.
The instance IAM role grants only the bedrock: InvokeModel permission and access to one S3 bucket.
An HTTP health check runs on /health. Auto scaling is set to a minimum of 1 and a maximum of 3 instances, since weekday mornings are the peak.
CloudWatch logs and alarms cover errors, LLM latency, and a monthly Bedrock budget.
What I am doing differently from Application

A different domain and a different kind of AI. App #1 App #1, ClauseCompass AI, is a contract-review copilot that flags risky clauses against a playbook and suppresses any finding it cannot cite from the document.. App #2 combines predictive ML (forecasting and optimization) with generative AI (document understanding), and the two feed each other.
Spec before code. I will write the data schema, the API contract, and the CLAUDE.md file before prompting any agent.
Deploy in week 1. Skeletons for both services go live on App Runner early, so networking, secrets, and health-check issues surface right away rather than at the end.
Measure the AI, not just ship it.
A golden test set of 50 real manifests, with a target of at least 95% field-level extraction accuracy.
Forecast backtesting against a seasonal-naive baseline.
Human-in-the-loop by design. Coordinators approve every allocation.
Security and cost from day one. IAM roles instead of keys, Cognito roles, Secrets Manager, and a Bedrock budget alarm.
