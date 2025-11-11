#!/usr/bin/env bash
# ABOUTME: Download research PDFs from arXiv for ARBS mathematical reference library
# ABOUTME: Downloads 16 papers on covariance, optimization, alpha generation, and risk modeling

set -e  # Exit on error

BASE_DIR="/home/user/ARBS/docs/papers"
mkdir -p "$BASE_DIR"

echo "========================================="
echo "ARBS Research PDF Downloader"
echo "========================================="
echo ""
echo "Downloading 16 papers from arXiv..."
echo ""

# Covariance Estimation & Shrinkage
echo "=== Covariance Estimation & Shrinkage (3 papers) ==="
mkdir -p "$BASE_DIR/covariance-estimation"
cd "$BASE_DIR/covariance-estimation"

echo "[1/16] Ledoit-Wolf with Unknown Mean (2023)..."
curl -L -o "ledoit-wolf-unknown-mean-2023.pdf" "https://arxiv.org/pdf/2304.07045.pdf"

echo "[2/16] Shrinkage with High Frequency Data (2016)..."
curl -L -o "shrinkage-high-frequency-2016.pdf" "https://arxiv.org/pdf/1611.06753.pdf"

echo "[3/16] Covariance under Total Positivity (2019)..."
curl -L -o "total-positivity-2019.pdf" "https://arxiv.org/pdf/1909.04222.pdf"

# Transaction Costs & Optimization
echo ""
echo "=== Transaction Costs & Optimization (3 papers) ==="
mkdir -p "$BASE_DIR/transaction-costs"
cd "$BASE_DIR/transaction-costs"

echo "[4/16] Quadratic Transaction Costs (2020)..."
curl -L -o "quadratic-costs-2020.pdf" "https://arxiv.org/pdf/2001.01612.pdf"

echo "[5/16] Cost-aware Large Universe (2024)..."
curl -L -o "cost-aware-large-universe-2024.pdf" "https://arxiv.org/pdf/2412.11575.pdf"

echo "[6/16] Fast QP for Mean-Variance (2022)..."
curl -L -o "fast-qp-2022.pdf" "https://arxiv.org/pdf/2212.06983.pdf"

# Alpha Generation & Signal Processing
echo ""
echo "=== Alpha Generation & Signal Processing (4 papers) ==="
mkdir -p "$BASE_DIR/alpha-generation"
cd "$BASE_DIR/alpha-generation"

echo "[7/16] AlphaForge (2024)..."
curl -L -o "alphaforge-2024.pdf" "https://arxiv.org/pdf/2406.18394.pdf"

echo "[8/16] 101 Formulaic Alphas (2016)..."
curl -L -o "101-alphas-2016.pdf" "https://arxiv.org/pdf/1601.00991.pdf"

echo "[9/16] AlphaAgent with LLM (2025)..."
curl -L -o "alphaagent-2025.pdf" "https://arxiv.org/pdf/2502.16789.pdf"

echo "[10/16] LLM Strategy Finding (2024)..."
curl -L -o "llm-strategy-finding-2024.pdf" "https://arxiv.org/pdf/2409.06289.pdf"

# Risk Modeling & Performance
echo ""
echo "=== Risk Modeling & Performance (3 papers) ==="
mkdir -p "$BASE_DIR/risk-modeling"
cd "$BASE_DIR/risk-modeling"

echo "[11/16] Risk Budgeting Portfolios (2025)..."
curl -L -o "risk-budgeting-2025.pdf" "https://arxiv.org/pdf/2504.19980.pdf"

echo "[12/16] Inverse Portfolio Optimization (2024)..."
curl -L -o "inverse-optimization-2024.pdf" "https://arxiv.org/pdf/2510.06986.pdf"

echo "[13/16] Multi-Asset Portfolio (2025)..."
curl -L -o "multi-asset-2025.pdf" "https://arxiv.org/pdf/2505.07537.pdf"

# Advanced Topics
echo ""
echo "=== Advanced Topics (3 papers) ==="
mkdir -p "$BASE_DIR/advanced"
cd "$BASE_DIR/advanced"

echo "[14/16] Robust Covariance & CVaR (2024)..."
curl -L -o "robust-cvar-2024.pdf" "https://arxiv.org/pdf/2406.00610.pdf"

echo "[15/16] Decision-Focused Learning for GMV (2025)..."
curl -L -o "decision-focused-learning-2025.pdf" "https://arxiv.org/pdf/2508.10776.pdf"

echo "[16/16] Optimal Cross-Validation (2025)..."
curl -L -o "optimal-cross-validation-2025.pdf" "https://arxiv.org/pdf/2503.15186.pdf"

echo ""
echo "========================================="
echo "✓ Download Complete!"
echo "========================================="
echo ""
echo "Downloaded 16 papers to: $BASE_DIR"
echo ""
echo "Directory structure:"
find "$BASE_DIR" -type f -name "*.pdf" | sort
echo ""
echo "Total size:"
du -sh "$BASE_DIR"
echo ""
echo "Next: Run PDF processing agents to extract mathematical content"
echo "See: docs/PDF_PROCESSING_PLAN.md"
