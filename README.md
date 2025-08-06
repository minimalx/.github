# 📦 Minimal .github Repository

This repository contains shared GitHub Actions **workflow templates** used across Minimal's repositories to ensure consistency, maintainability, and best practices in CI/CD and project automation.

## 🧩 Overview

The `.github` repo centralizes reusable workflow templates for:

- Continuous Integration (CI)
- Deployment pipelines
- Linting & formatting
- Code quality and testing
- Automated releases
- Labeling and automation bots

These workflows can be **referenced** from other repositories using `uses:` and version pinning for reliability.

## 📁 Structure

```bash
.github/
├── workflow-templates/
│   └── reusable-<workflow-name>.yml   # Template workflows
├── ISSUE_TEMPLATE/
│   └── bug_report.md
│   └── feature_request.md
├── PULL_REQUEST_TEMPLATE.md
└── CODEOWNERS
