# Milestone Management: Enterprise Project Management Web Application

A full-stack Project Management Web Application featuring interactive Gantt scheduling, multi-view workspaces, Critical Path Method (CPM), baseline variance tracking, Kanban board, team workload capacity, Earned Value Management (EVM), and formatted Excel (.xlsx) import/export.

---

## 🌟 Comprehensive Feature Suite

### 1. 📊 Interactive Gantt Workspace & Work Breakdown Structure (WBS)
- **Dual-Pane Layout**: Excel spreadsheet grid on the left synced with the interactive SVG timeline on the right.
- **WBS Indexing**: Automatic hierarchical numbering (`1.0`, `1.1`, `1.1.1`).
- **Drag-to-Move & Drag-to-Resize**: Reschedule dates or extend duration directly on the timeline.
- **Milestones**: Zero-duration milestone indicators rendered as glowing diamond markers.
- **Timeline Zoom Levels**: Switch between **Day**, **Week**, **Month**, and **Year** perspectives.

### 2. 🎯 Critical Path Method (CPM) & Float Calculation
- **Forward & Backward Pass Engine**: Automatically computes Early Start (`ES`), Early Finish (`EF`), Late Start (`LS`), and Late Finish (`LF`).
- **Total Float (Slack)**: Computes available slack time before project completion is impacted.
- **Visual Critical Path Highlighting**: Clicking the **Critical Path** toggle highlights all critical tasks with a glowing red/rose aura on the Gantt timeline and adds CPM tags on the grid.

### 3. 📸 Baseline vs. Actual Schedule Tracking
- **Snapshot Baselines**: Click **Snap Baseline** to record planned target dates.
- **Variance Tracking**: Automatic calculation of **Schedule Variance (days)**.
- **Visual Comparison**: Slipped tasks are highlighted to reveal schedule risk.

### 4. 📋 Interactive Kanban Board
- **4 Workflow Columns**: *Not Started*, *In Progress*, *Delayed / Critical*, and *Complete*.
- **Drag & Drop**: Move task cards across columns to update task status and progress in real time.

### 5. 👥 Team Workload & Capacity Heatmap
- **Capacity Balancing**: Real-time aggregation of total tasks, estimated hours, and realized hours per team member.
- **Over-allocation Alerts**: Flags team members with heavy task overlaps.

### 6. 💰 Financials & Earned Value Management (EVM - INR ₹)
- Tracks **Planned Value (PV)**, **Earned Value (EV)**, and **Actual Cost (AC)** in Indian Rupees (**INR - `₹`**).
- Real-time **Cost Performance Index (CPI)** and **Schedule Performance Index (SPI)** indicators.
- Indian Numbering System formatting (Lakhs / Crores, e.g. `₹25,00,000`, `₹1,50,000`).

### 7. 📑 Formatted Excel (.xlsx) Export & Import (Indian Standard)
- **Export**: One-click download of stylized Excel spreadsheets with Indian Rupee formatting (`₹#,##,##0.00`), **DD/MM/YYYY** dates, and effort in **Man-Hours**.
- **Import**: Ingest tasks and dates supporting both **DD/MM/YYYY** and ISO formats.

### 8. 💬 Task Comments, Attachments & Activity Audit Trail
- Multi-tab Task Drawer: **Details**, **Dependencies**, **Cost & Effort**, and **Comments**.
- Full chronological activity feed tracking all changes.

### 9. 👥 Team & User Management (`/team/`)
- **Add Team Members**: Create new team users with First/Last Name, Username ID, Email, Role, and Password.
- **Edit & Delete Users**: Safe deletion with task unassignment protection.
- **Workload & Assignment Integration**: Direct tracking of assigned tasks, active tasks, estimated hours, and actual hours across all projects.

### 10. 💾 SQLite Database Import & Export in Django Admin (`/admin/`)
- **1-Click Database Export**: Download the live, complete `db.sqlite3` file as a timestamped backup (`milestone_db_backup_YYYY-MM-DD.sqlite3`) directly from Django Admin.
- **Safe Database Import (Restore)**: Upload any `.sqlite3`, `.db`, or `.sqlite` file with pre-flight format validation and `PRAGMA integrity_check`.
- **Automatic Rollback Safeguard**: Automatically creates a rollback snapshot in `backups/pre_restore_backup_<timestamp>.sqlite3` before replacing data so no information is ever lost.
- **Rollback History & 1-Click Restore**: View, download, restore, or delete previous rollback snapshots directly from the admin dashboard.

---

### 11. 🌙 Pure Dark Theme Enforcement
- **Unified Dark Mode**: Strict, sleek dark palette across all views, panes, modals, and tables (`bg-slate-950`, `bg-slate-900`, `bg-slate-850`).
- **Eliminated Visual Inconsistencies**: Fixed unstyled table headers (`.excel-grid-header`), parent task rows, KPI cards, and modals that previously reverted to washed-out or white backgrounds.
- **Removed Theme Toggle Switcher**: Guaranteed fixed, uniform dark theme presentation with zero light-mode flashes or mismatched elements.

---

## 🚀 Quick Launch

### Running the App:
- **Double-click**: `run_app.bat` (or `start.bat`)
- **Terminal**: `python manage.py runserver 127.0.0.1:8000`

---

## 🧪 Automated Test Suite

All 66 automated unit and integration tests passed:
```
Ran 66 tests in 21.448s

OK
```

