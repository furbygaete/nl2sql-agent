# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Added query-result export buttons in `src/nl2sql_agent/web.py` for `.xlsx` and `.pdf` downloads in the `/gui` chat interface.
- Added Oracle schema-introspection tools in `src/nl2sql_agent/tools.py` for packages, functions, procedures, views, and materialized views (`get_package_source`, `get_function_source`, `get_procedure_source`, `get_view_definition`, `get_materialized_view_definition`).

### Changed
- Updated chart and file-export behavior to be explicit-intent only: chart image events are emitted/rendered only for chart/image requests, and download buttons are shown only for explicit export/download requests.

### Changed
- Extended tabular result export in `/gui` from CSV-only to a multi-format export flow (`.csv`, `.xlsx`, `.pdf`) for SQL tool results.
- Updated `README.md` to document the new multi-format export capability in the chat UI.
