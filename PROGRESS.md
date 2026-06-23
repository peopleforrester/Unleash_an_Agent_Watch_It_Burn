# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- (2026-06-22) Created the observability meta-PRD (GitHub issue #7, `prds/7-observability-meta.md`): 8 self-contained milestones that each produce a research synthesis or a child PRD covering one area of the observability strategy for the Watch It Burn workshop. Each milestone is executable by a cold AI instance — it lists its own reads, design decisions, and child-PRD creation steps. Decisions are documented in each child PRD's Decision Log rather than separate planning docs.
- (2026-06-22) Created `prds/` directory to hold PRD files; added a local `.gitignore` override since the global gitignore excludes `prds/`.
- (2026-06-22) Created `docs/ROADMAP.md` with forward-looking implementation order for observability PRDs.

### Changed
- (2026-06-22) Updated observability planning docs and research/23 to reflect that the TypeScript rewrite of guard-proxy is not happening — all Python apps stay Python, spiny-orb instrumentation is off the table, Decision 4 in research/23 closed as superseded.
