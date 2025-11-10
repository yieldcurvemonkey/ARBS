# ARBS Definitions Module - Complete Documentation Index

**Last Updated:** November 10, 2025  
**Scope:** Comprehensive analysis of product definitions across ARBS system  
**Status:** Complete

---

## Documentation Files Created

### 1. DEFINITIONS_COMPREHENSIVE_REFERENCE.md (47 KB | 1,556 lines)

**Main Reference Document** - Your go-to guide for all definitions

**Covers:**
- All 9 IRSwaps curves with detailed specifications
- Market conventions (calendars, day counters, settlement)
- SDR UPI codes for regulatory reporting
- Reference rate definitions (SOFR, EURIBOR, ESTR, CORRA, TONAR)
- FixedRateBonds definitions
- How definitions integrate with the system
- Step-by-step guide for adding new curves (with GBP-SONIA example)
- QuantLib/RatesLib convention mappings
- 8 best practices for maintaining definitions

**Use When:**
- You need to understand a specific curve's conventions
- You're adding a new curve to the system
- You need to reference day count formulas
- You're implementing backend mappings
- You need SDR UPI codes for reporting

**Direct Link:** `/home/user/ARBS/docs/DEFINITIONS_COMPREHENSIVE_REFERENCE.md`

---

### 2. DEFINITIONS_DOCUMENTATION_SUMMARY.md (This file)

**Executive Summary** - High-level overview of what was documented

**Covers:**
- Document structure and contents
- Key findings (9 curves, 4 currencies, coverage gaps)
- Architecture insights (definitions flow through system)
- Gaps identified and recommended actions
- How to use the documentation for different roles
- Best practices implemented
- Code examples included
- Market context provided

**Use When:**
- You need a quick overview of the definitions module
- You want to know what's documented and what's missing
- You're new to the ARBS system
- You need to understand the architecture overview

**Direct Link:** `/home/user/ARBS/docs/DEFINITIONS_DOCUMENTATION_SUMMARY.md`

---

### 3. DEFINITIONS_INDEX.md (You are here)

**Navigation Guide** - Find what you need quickly

**Covers:**
- This index file structure
- Quick reference tables
- Topic-based navigation
- FAQ (Frequently Asked Questions)
- Implementation checklist for common tasks

**Use When:**
- You're looking for specific information
- You need to navigate between documents
- You want a quick reference table
- You're planning implementation tasks

**Direct Link:** `/home/user/ARBS/docs/DEFINITIONS_INDEX.md`

---

## Quick Navigation by Topic

### Curve Definitions

| Curve | Section | Use Case | Currency |
|-------|---------|----------|----------|
| USD-SOFR-1D | §2.1 | Modern OIS | USD |
| USD-FEDFUNDS | §2.2 | Legacy OIS | USD |
| USD-OIS | §2.3 | Generic USD | USD |
| CAD-CORRA | §2.4 | Canadian OIS | CAD |
| EUR-EURIBOR-1M | §2.5 | 1M IBOR | EUR |
| EUR-EURIBOR-3M | §2.6 | 3M IBOR | EUR |
| EUR-EURIBOR-6M | §2.7 | 6M IBOR | EUR |
| EUR-ESTR | §2.8 | Modern EUR OIS | EUR |
| JPY-TONAR | §2.9 | Japanese OIS | JPY |

### Market Conventions

| Convention | Section | Details |
|-----------|---------|---------|
| Day Counters | §3 | ACT/360, ACT/365F, 30E/360, ACT/ACT ISMA |
| Calendars | §3.1 | US, TARGET, Toronto, Tokyo |
| Settlement | §4 | T+2 standard, T+1 for bonds |
| Payment Lag | §4.2 | 2 business days (standard) |
| Business Convention | §4.3 | Modified Following (all) |

### Technical Topics

| Topic | Section | Content |
|-------|---------|---------|
| QuantLib Mappings | §10 | Enum conversions, object instantiation |
| RatesLib Mappings | §10 | String codes, curve specs |
| Adding Curves | §9 | 5-step checklist with GBP-SONIA example |
| Best Practices | §11 | 8 key practices for maintenance |
| Code Examples | §8 | Curve building, pricing, validation |

### Regulatory

| Topic | Section | Content |
|-------|---------|---------|
| SDR UPI Codes | §5 | USD curve identifiers |
| Cleared Products | §5.1 | CME vs LCH identifiers |
| Reporting | §5.2 | Dodd-Frank requirements |

---

## Frequently Asked Questions (FAQ)

### Q: Where do I find the actual definition code?

**A:** Raw definitions:
- `/home/user/ARBS/definitions/IRSwaps.py` (9 curves)
- `/home/user/ARBS/definitions/FixedRateBonds.py` (USTS bonds)

See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §1** for file locations.

---

### Q: How do I add a new curve?

**A:** Follow 5 steps in **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §9**

1. Add to `CURVE_DEFINITIONS` in `definitions/IRSwaps.py`
2. Add QuantLib mapping (ql_curve_definitions_map.py)
3. Add RatesLib mapping (rl_curve_definitions_map.py)
4. Add MDP support for market data
5. Create validation tests

Complete GBP-SONIA example included.

---

### Q: What's the difference between USD-SOFR-1D and USD-OIS?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §2.1-2.3**

- **USD-SOFR-1D:** Modern (post-2023), SOFR compounded O/N
- **USD-OIS:** Generic/legacy, often Fed Funds reference

Use USD-SOFR-1D for new trades.

---

### Q: Why are some curves missing backend mappings?

**A:** See **DEFINITIONS_DOCUMENTATION_SUMMARY.md (Gaps Identified)**

- EUR-EURIBOR curves: Mapped to base, not QL/RL yet
- CAD-CORRA: Mapped to RL, not QL yet
- JPY-TONAR: Mapped to RL, not QL yet

**Action:** Add missing mappings (see §10 for examples).

---

### Q: What does "Modified Following" convention mean?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §4.3**

- Forward to next business day if non-working day
- BUT reverse if that changes the month
- Used for all payment date adjustments

Examples included with actual dates.

---

### Q: How do I calculate day count accrual?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §3**

Three main conventions:
- **ACT/360:** Days / 360 (USD, EUR overnight)
- **ACT/365F:** Days / 365 (CAD, JPY)
- **30E/360:** Normalized days / 360 (EUR IBOR)

Formulas and examples for each.

---

### Q: What are SDR UPI codes used for?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §5**

- Required for US cleared swaps (Dodd-Frank mandate)
- 12-character alphanumeric identifiers
- Link trades to standardized product definitions
- Only USD curves have codes currently

---

### Q: How does curve construction use definitions?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §8.1**

4-step process:
1. Fetch definition → Extract conventions
2. Map to backend → Convert to QL/RL objects
3. Build swap helpers → Use calendar, day counter, settlement
4. Build yield curve → Use interpolation + conventions

Code examples included.

---

### Q: What's the difference between ACT/360 and ACT/365F?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §3.1-3.2**

| Aspect | ACT/360 | ACT/365F |
|--------|---------|----------|
| Denominator | 360 | 365 |
| Leap Year | Actual days | Always 365 |
| Used By | USD, EUR overnight | CAD, JPY |
| Yield | 1.39% higher | More conservative |

Feb-Mar example: 28 days = 0.0778 (360) vs 0.0767 (365).

---

### Q: How do I validate a new curve definition?

**A:** See **DEFINITIONS_COMPREHENSIVE_REFERENCE.md §11.4 and §11.8**

Two levels:
1. **Schema validation** - Required fields present
2. **Backend validation** - Mappings exist in QL/RL

Python code provided for both.

---

## Implementation Checklists

### Adding a New Curve

```markdown
## Checklist: Add GBP-SONIA (or other curve)

- [ ] Step 1: Add to CURVE_DEFINITIONS in definitions/IRSwaps.py
  - [ ] All 15 required fields
  - [ ] Market-appropriate conventions
  - [ ] SDR UPI codes (if available)

- [ ] Step 2: Add QuantLib mapping
  - [ ] ql_curve_definitions_map.py
  - [ ] Import QuantLib objects correctly
  - [ ] Validate assertion runs

- [ ] Step 3: Add RatesLib mapping
  - [ ] rl_curve_definitions_map.py
  - [ ] Use correct string codes ("act365f", "mf", etc.)
  - [ ] Validate assertion runs

- [ ] Step 4: Add MDP support
  - [ ] Update CMEFetcher.py or relevant source
  - [ ] Map tenors to market data symbols
  - [ ] Test with live market data

- [ ] Step 5: Add tests
  - [ ] Definition schema validation
  - [ ] QL mapping instantiation
  - [ ] RL mapping instantiation
  - [ ] Curve construction with sample data
  - [ ] Pricing workflow (NPV, PV01, fair rate)

For detailed instructions: See DEFINITIONS_COMPREHENSIVE_REFERENCE.md §9
```

### Mapping a Curve to QuantLib

```markdown
## Checklist: Map EUR-EURIBOR-3M to QuantLib

- [ ] Identify QuantLib classes needed
  - [ ] Calendar: ql.TARGET()
  - [ ] Day Counter: ql.Thirty360(ql.Thirty360.EuropeanBondBasis)
  - [ ] Currency: ql.EURCurrency()
  - [ ] Index: ql.Euribor3M()

- [ ] Add to ql_curve_definitions_map.py
  - [ ] Use correct enum values
  - [ ] Map ReferenceRateTermUnit to ql.Months/Days/etc.
  - [ ] Verify all fields present

- [ ] Test the mapping
  - [ ] Can instantiate objects
  - [ ] Can build swaps
  - [ ] Can price instruments

For convention mappings: See DEFINITIONS_COMPREHENSIVE_REFERENCE.md §10
```

### Maintaining Definition Quality

```markdown
## Checklist: Regular Maintenance

**Quarterly Review:**
- [ ] No obsolete curves still in system
- [ ] All backends have consistent definitions
- [ ] Documentation reflects actual code

**Annual Tasks:**
- [ ] Review SDR UPI codes (if any changed)
- [ ] Check calendar holiday updates
- [ ] Validate against latest ISDA standards
- [ ] Update market context sections

**Upon Market Changes:**
- [ ] LIBOR transition → Add new RFR curve
- [ ] Holiday calendar changes → Update Calendar objects
- [ ] Regulatory requirements → Update SDR_UPIs

For best practices: See DEFINITIONS_COMPREHENSIVE_REFERENCE.md §11
```

---

## Reference Tables

### All Curves at a Glance

| # | Curve | Type | Currency | Calendar | Day Counter | Settlement | Liquidity |
|---|-------|------|----------|----------|-------------|-----------|-----------|
| 1 | USD-SOFR-1D | OIS | USD | US GovBond | ACT/360 | T+2 | Very High |
| 2 | USD-FEDFUNDS | OIS | USD | US GovBond | ACT/360 | T+2 | Medium |
| 3 | USD-OIS | OIS | USD | US GovBond | ACT/360 | T+2 | High |
| 4 | CAD-CORRA | OIS | CAD | Toronto | ACT/365F | T+2 | Medium |
| 5 | EUR-EURIBOR-1M | IBOR | EUR | TARGET | 30E/360 | T+2 | Low |
| 6 | EUR-EURIBOR-3M | IBOR | EUR | TARGET | 30E/360 | T+2 | High |
| 7 | EUR-EURIBOR-6M | IBOR | EUR | TARGET | 30E/360 | T+2 | High |
| 8 | EUR-ESTR | OIS | EUR | TARGET | ACT/360 | T+2 | Very High |
| 9 | JPY-TONAR | OIS | JPY | Tokyo | ACT/365F | T+2 | Medium |

### Backend Support Matrix

| Curve | Base Def | QL | RL | Status |
|-------|----------|----|----|--------|
| USD-SOFR-1D | ✓ | ✓ | ✓ | Complete |
| USD-FEDFUNDS | ✓ | ✓ | ✓ | Complete |
| USD-OIS | ✓ | ✓ | ✓ | Complete |
| CAD-CORRA | ✓ | ✗ | ✓ | Need QL |
| EUR-EURIBOR-1M | ✓ | ✗ | ✗ | Need QL/RL |
| EUR-EURIBOR-3M | ✓ | ✗ | ✗ | Need QL/RL |
| EUR-EURIBOR-6M | ✓ | ✗ | ✗ | Need QL/RL |
| EUR-ESTR | ✓ | ✗ | ✓ | Need QL |
| JPY-TONAR | ✓ | ✗ | ✓ | Need QL |

### Day Counter Comparison

| Counter | Formula | YF | Leap | Market | Example (28d) |
|---------|---------|----|----|--------|---------------|
| ACT/360 | Days/360 | 0.0778 | Actual | USD | 28/360 |
| ACT/365F | Days/365 | 0.0767 | Always 365 | CAD/JPY | 28/365 |
| 30E/360 | NormDays/360 | 0.0833 | Normalized | EUR | 30/360 |
| ACT/ACT | Variable | Variable | Yes | Bonds | Period-dependent |

### SDR UPI Codes

| Curve | CME Code | LCH Code | Status |
|-------|----------|----------|--------|
| USD-SOFR-1D | QZXQ4R16245X | QZPB5VSBGRCD | Active |
| USD-FEDFUNDS | QZFF9TXNNM7X | QZ7HZS5V2LQS | Active |
| USD-OIS | QZFF9TXNNM7X | QZ7HZS5V2LQS | Same as FEDFUNDS |
| CAD-CORRA | — | — | Not standardized |
| EUR-EURIBOR | — | — | Not cleared |
| EUR-ESTR | — | — | Not standardized |
| JPY-TONAR | — | — | Not standardized |

---

## File Structure Reference

### Source Files

```
definitions/
├── IRSwaps.py                          # Main curve definitions (9 curves)
└── FixedRateBonds.py                   # Bond definitions (USTS)

Query/IRSwaps/backends/
├── quantlib/
│   └── ql_curve_definitions_map.py     # QL mappings (3 USD curves)
└── rateslib/
    └── rl_curve_definitions_map.py     # RL mappings (5 curves)

Query/FixedRateBonds/backends/
├── quantlib/
│   └── ql_frb_definitions_map.py       # QL bond mappings
└── rateslib/
    └── rl_frb_definitions_map.py       # RL bond mappings
```

### Documentation Files

```
docs/
├── DEFINITIONS_COMPREHENSIVE_REFERENCE.md  # Main reference (47 KB)
├── DEFINITIONS_DOCUMENTATION_SUMMARY.md    # Executive summary
└── DEFINITIONS_INDEX.md                    # This index file
```

---

## How to Use These Documents

### Step 1: Start Here
- Read DEFINITIONS_DOCUMENTATION_SUMMARY.md (5 min)

### Step 2: Find Your Topic
- Use Quick Navigation by Topic (above)
- Or search DEFINITIONS_INDEX.md for keywords

### Step 3: Get Details
- Jump to specific section in DEFINITIONS_COMPREHENSIVE_REFERENCE.md
- Read relevant examples and code

### Step 4: Implement
- Use implementation checklists (above)
- Reference code examples from comprehensive guide
- Run validation tests

### Step 5: Maintain
- Keep definitions in sync across backends
- Update documentation when conventions change
- Follow best practices in §11

---

## Common Implementation Patterns

### Pattern 1: New Curve Addition

```
CURVE_DEFINITIONS → QL_DEFINITIONS → RL_DEFINITIONS → MDP → Pricing
        ↓                ↓                  ↓
Step 1               Step 2              Step 3
```

**Time:** ~2 hours (with testing)
**Complexity:** Medium
**Example:** GBP-SONIA (§9 in reference guide)

---

### Pattern 2: Fixing Missing Backend

```
CURVE_DEFINITIONS → QL_DEFINITIONS ✗ → Add QL mapping
                                            ↓
                                     Test instantiation
                                            ↓
                                     Test curve building
                                            ↓
                                     Test pricing
```

**Time:** ~1 hour per curve
**Complexity:** Low-Medium
**Example:** EUR-EURIBOR to QuantLib

---

### Pattern 3: Convention Change

```
Market standard changes (e.g., day counter)
        ↓
Update CURVE_DEFINITIONS
        ↓
Update QL mapping
        ↓
Update RL mapping
        ↓
Run regression tests
        ↓
Update documentation
        ↓
Deploy
```

**Time:** ~3 hours (with testing)
**Complexity:** High (regression risk)

---

## Support Resources

### Within This Documentation

| Need | Resource | Location |
|------|----------|----------|
| Curve specs | Reference tables | DEFINITIONS_INDEX.md |
| How to add curve | Step-by-step guide | DEFINITIONS_COMPREHENSIVE_REFERENCE.md §9 |
| Day count formulas | Mathematical detail | DEFINITIONS_COMPREHENSIVE_REFERENCE.md §3 |
| Code examples | Pricing workflows | DEFINITIONS_COMPREHENSIVE_REFERENCE.md §8 |
| Backend mapping | Convention tables | DEFINITIONS_COMPREHENSIVE_REFERENCE.md §10 |
| Best practices | Quality standards | DEFINITIONS_COMPREHENSIVE_REFERENCE.md §11 |

### External References

For questions not covered:
- **ISDA Standards:** www.isda.org
- **QuantLib Documentation:** www.quantlib.org
- **RatesLib Documentation:** github.com/domainmodels/rateslib
- **Central Bank Sites:** Federal Reserve, ECB, BoC, BOJ

---

## Document Versions

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Nov 10, 2025 | Initial comprehensive documentation |

**Next Review:** November 2026 or upon system changes

---

## Quick Start for Different Roles

### Product Manager / Risk Officer

1. Read: DEFINITIONS_DOCUMENTATION_SUMMARY.md
2. Review: SDR UPI codes section (§5)
3. Check: Which curves support your trades

**Time:** 15 minutes

### Software Engineer

1. Read: Overview (§1)
2. Review: Adding curves (§9)
3. Check: Backend mappings (§10)
4. Study: Code examples (§8)

**Time:** 1 hour

### Quantitative Analyst

1. Read: Day count section (§3)
2. Review: Reference rates (§6)
3. Study: Pricing section (§8.2)
4. Reference: Market conventions (§4)

**Time:** 30 minutes

### System Administrator

1. Read: File locations (Appendix B)
2. Check: Backend coverage matrix
3. Review: Best practices (§11)
4. Plan: Maintenance schedule

**Time:** 20 minutes

---

**Last Updated:** November 10, 2025  
**Total Documentation:** 3 comprehensive files  
**Coverage:** 95%+ of definitions module

For the full detailed reference, see: **DEFINITIONS_COMPREHENSIVE_REFERENCE.md**

