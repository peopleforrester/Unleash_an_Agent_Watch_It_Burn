# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- (2026-06-22) Created observability meta-PRD (`prds/00-observability-meta.md`) defining 8 child PRDs to be created in dependency order, covering the full observability strategy for the Watch It Burn workshop. Each milestone is a structured design conversation with Whitney followed by child PRD creation.
- (2026-06-22) Created `docs/planning/` directory for per-PRD planning and design decision documentation.
- (2026-06-22) Created `prds/` directory to hold all PRD files.
- (2026-06-22) Created `docs/ROADMAP.md` with forward-looking implementation order for observability PRDs.

### Changed
- (2026-06-22) Updated observability planning docs and research/23 to reflect that the TypeScript rewrite of guard-proxy is not happening — all Python apps stay Python, spiny-orb instrumentation is off the table, Decision 4 in research/23 closed as superseded.
