# Database Architecture Full Expansion (ER Diagram) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full 5-entity database architecture from the user's ER diagram (`USERS`, `AUDIT_PROJECTS`, `DOCUMENTS`, `MATCH_RESULTS`, `LLM_LOGS`) in PostgreSQL with full backward compatibility and automated test coverage.

**Architecture:** Use SQLAlchemy models in `db.py` mapping to `users`, `audit_projects`, `documents`, `match_results`, `llm_logs`. Maintain seamless backward compatibility for existing code via aliases (`Project = AuditProject`, `AuditItem = MatchResult`). Update Flask endpoints in `web/web_app.py` to persist documents and LLM logs upon project saving.

**Tech Stack:** Python 3.12, PostgreSQL 17, SQLAlchemy 2.0+, Werkzeug security, Flask.

**Spec:** User uploaded ER diagram `media_1795288250786_f96a8674.png`.

## Global Constraints

- Table names must strictly follow the ER diagram: `users`, `audit_projects`, `documents`, `match_results`, `llm_logs`.
- Column names must strictly follow the ER diagram.
- 100% backward compatibility with existing tests (`test_auth_db.py`, `test_web_api_auth.py`, `test_suite.py`) and API clients.
- PostgreSQL 17 foreign key cascading (`ondelete="CASCADE"`).

## Review Focus

1. Cascade deletions: deleting an `AuditProject` must cascade-delete all its `documents`, `match_results`, and `llm_logs`.
2. Safe migration: cleanly drop empty legacy tables `audit_items` and `projects` if they exist without breaking existing users.
3. Compatibility properties: `status` <-> `upper_status`, `similarity` <-> `text_sim`, `items` <-> `match_results`.
4. LLM logs persistence: recording token usage, cost in RUB, and confidence when LLM arbitration runs.
5. Error handling: rollback on database exceptions.

---

### Tasks

- [ ] **Task 1: Update `db.py` with the full 5-entity ER schema and aliases**
  - Define `User` (`users`)
  - Define `AuditProject` (`audit_projects`), with alias `Project = AuditProject`
  - Define `Document` (`documents`)
  - Define `MatchResult` (`match_results`), with alias `AuditItem = MatchResult`
  - Define `LLMLog` (`llm_logs`)
  - Add `init_db()` migration logic to drop old empty tables if present and create new tables
  - Provide `.to_dict()` methods for all models

- [ ] **Task 2: Update `test_auth_db.py` to test all 5 entities**
  - Add test for `Document` creation and relationship with `AuditProject`
  - Add test for `LLMLog` creation and relationship with `AuditProject`
  - Add test for `MatchResult` with `upper_status`, `detail_class`, `formulation_warn`, `financial_risk`
  - Verify cascade delete when a project is deleted

- [ ] **Task 3: Update `web/web_app.py` project API endpoints**
  - Update `/api/projects/save` to create `Document` entries (for VOR and LSR)
  - Update `/api/projects/save` to record `LLMLog` entries when AI arbitration stats or items are present
  - Update `/api/projects/<id>` to include `documents` and `llm_logs` in the JSON response
  - Ensure compatibility with `/api/projects/item_decision`

- [ ] **Task 4: Update `test_web_api_auth.py` and run full test verification**
  - Update web API tests to assert documents and LLM logs in project save & get
  - Run `python -m unittest test_auth_db.py test_web_api_auth.py`
  - Run `python -m unittest test_suite.py`
  - Commit changes to git and push to `origin/main`
