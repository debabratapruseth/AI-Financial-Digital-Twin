# Assumptions and calibration requirements

All data is synthetic and monetary values are USD billions. The illustrative balance sheet totals $100bn of assets and is not tied to a real institution.

- Securities receive one uniform 15% HQLA haircut; eligibility and regulatory levels are not modeled.
- Baseline and stressed withdrawals are cohort averages with linear sensitivities.
- The simplified LCR uses aggregated outflows and one inflow cap, not regulatory cash-flow categories.
- RWA is loans times a fixed 72% density; modeled losses are deducted directly from CET1.
- FX uses linear spot revaluation of unhedged exposure. Basis, options, rates, and nonlinear Greeks are excluded.
- Volatility, outage, backlog, customer impact, and margin effects use transparent scalar sensitivities.
- Credit PD stress is multiplicative; collateral is descriptive and LGD already represents recovery assumptions.
- Payment flows are hourly normally distributed aggregate values; capacity and failover are simplified.
- The dedicated eight-hour cloud scenario assumes zero processing capacity before backup activation, 70% capacity from hours 3–8, and 125% temporary processing capacity after primary recovery until the backlog clears. The 125% recovery capacity is explicit and illustrative.
- Identity Service and Domestic Payments have synthetic Region B standby deployments; Cross-Border Payments has no backup. Other applications use synthetic primary/backup data-centre placements. At backup activation, downstream channel applications recover at the capacity of their restored critical dependency.
- Outage-driven withdrawal response equals the configured 5% response scale × calculated service unavailability × dependency impact × segment outage sensitivity.
- Drawn liquidity facilities accrue a 4.5% annualized prototype cost for 30 days; unmet emergency funding accrues 5% annualized for 30 days.
- Liquid-asset sales use a 2% execution haircut; the haircut is a realized P&L loss while sale proceeds affect liquidity.
- Dependency impact uses configured edge weights and maximum-path impact, not empirically estimated causality.
- Monte Carlo distributions are illustrative, bounded, and not calibrated to historical tails.
- A recovery-time warning is greater than four hours and critical is greater than eight hours. These are prototype decision thresholds, not regulatory standards.

Production use would require bank-specific product/runoff segmentation, behavioral calibration, legal-entity and currency ladders, collateral and encumbrance detail, market revaluation, credit migration/default dependence, operational telemetry, vendor SLAs, customer response research, extreme-value calibration, validation, back-testing, governance, and regulatory sign-off.
