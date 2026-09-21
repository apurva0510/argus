# Predictive Signal Research

## Question

Can a dated model rank Argus companies by whether they will outperform QQQ over
the next 20 trading sessions? The outcome is measured from the signal day's
adjusted close. It is a research label, not an executable trade return.

## Data and validation

- Source: read-only production Supabase history through 2026-09-18.
- 14,010 labeled, non-benchmark company-days with the required core metrics.
- Four expanding training windows, each followed by a disjoint test window.
  Training examples whose 20-session outcomes overlap a test start are excluded.
- Test windows: 2026-01-12–03-06, 03-09–04-30, 05-01–06-25, and 06-26–08-20.
- Only dated price-derived metrics and QQQ context are used. Fundamentals,
  valuation, theme exposure, and news are excluded until their historical
  availability can be verified.

## Feature search results

The strongest consistent *ranking* model in this exploratory search was a small
random forest using company 20-day volatility and QQQ 1-month return, 3-month
return, and 20-day volatility. Its test AUCs were 0.593, 0.548, 0.552, and 0.606
(mean 0.575). Mean Brier score was 0.248. A larger technical-plus-market forest
had mean AUC 0.541 and mean Brier 0.251; momentum-only and pullback-only models
were weaker. In the latest test window, permuting company volatility reduced AUC
by 0.070 and QQQ 1-month return by 0.034. These are correlated-feature
diagnostics, not causal importance estimates.

The small model's daily top-five hit rates were 61.6%, 60.0%, 61.1%, and 36.4%.
The last period's full-universe hit rate was 42.0%, and the top-five mean excess
return was -2.32%. Good overall ranking did not translate into reliable top-five
selection during that period. The four tests share the same underlying market
history, and feature sets were chosen after seeing these results, so they are not
an untouched confirmation set.

Inside a pullback zone (52-week drawdown at least 10% and RSI no more than 55),
the small model's AUC ranged from 0.524 to 0.587. Outside that zone it ranged
from 0.525 to 0.641. This supports evaluating a broader watchlist research view
before confining predictions to Pullback Finder.

## Product decision

Keep the model offline. The product gate is at least **70% held-out hit rate**
for the daily top five in every evaluation window. None of the tested models
passes it. The strongest ranking model reached only 36.4% in the latest window.
If later data support a model that passes the gate, the best first UI location
to evaluate is a **watchlist research view** covering the full non-benchmark
universe. Avoid a buy/sell label or an uncalibrated probability.

## Next validation gates

1. Freeze a feature set and model, then require the 70% hit-rate gate on
   genuinely new dates before adding it to the app.
2. Compare by sector and market regime, and report uncertainty by time block
   because company-day labels overlap heavily.
3. Validate signal-time data availability and adjusted-price revision effects.
4. Check probability calibration before displaying probabilities.
5. Compare against the current opportunity score on dates where that score is
   historically available.

## Focused pullback recovery experiment

The second experiment tested the narrower setup proposed after the broad model:
a company 10–25% below its 52-week high but still above its 200-day moving
average. Entry is the next session's open, adjusted using that day's
adjusted-close/close ratio. A healthy recovery beats QQQ by at least five
percentage points over 60 sessions and never closes 15% below entry along the
way. The event sampler spaces signals from the same company 60 sessions apart.

Only 139 matured events across 46 companies remain. The default chronological
split trains on 74 events and tests on 47, with a gap that excludes training
labels overlapping the test start. The test recovery rate was 27.7%. A five-input
logistic model (drawdown, RSI, distance from 200DMA, three-month QQQ-relative
return, and 20-day volatility) reached AUC 0.771, but only 6 of its 10
highest-ranked test events were healthy recoveries. Its estimated probabilities
never reached 70%. The fixed rule comparator hit 2 of 14 events. A shallow tree
performed worse.

Changing the chronological split to the newest 20% or 40% of event dates made
the logistic model's highest-fifth hit rate 33.3% or 50.0%. These are overlapping
sensitivity checks, not independent confirmation. No configuration reaches the
70% gate. The small sample and changing outcomes make this experiment unsuitable
for a user-facing prediction. The next substantive improvement requires more
independent history or a different, defensible target rather than a larger model.

## Downside screen selected for Watchlists

The useful narrower question is whether a company avoids closing 10% below a
next-session-open entry during the following 20 trading sessions. We use
adjusted opens and closes. Events from the same company are spaced at least
20 trading sessions apart. A 10-year yfinance price backfill was made into an
isolated SQLite research copy; it did not change the app database. This produced
4,378 matured events from September 2016 through August 2026.

A shallow tree estimated risk, but volatility alone matched or beat it at similar
coverage. We checked candidate cutoffs on the earliest training period
(September 2017–October 2021): **35% annualized 20-day volatility** was the
broadest tested cutoff with at least 70% avoidance and at least five percentage
points of improvement over that period's unscreened 79.3% rate. The final
screen uses this fixed rule. It only emits “Lower observed risk” for fresh,
non-benchmark metrics meeting the threshold; otherwise it abstains.

| Later test period | No-screen avoidance | Screen avoidance | Screen coverage | Events | Companies | Dates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nov 2021–Mar 2023 | 66.8% | 80.6% | 38.3% | 263 | 35 | 51 |
| Mar 2023–May 2024 | 80.0% | 89.0% | 53.7% | 355 | 38 | 56 |
| May 2024–Jul 2025 | 70.1% | 85.0% | 38.2% | 253 | 39 | 39 |
| Jul 2025–Aug 2026 | 70.3% | 88.7% | 25.1% | 160 | 32 | 36 |

All four expanding-window tests train only on outcomes matured before the test
start. Each passes the 70% hit-rate gate and includes many company events and
dates. This is a *downside avoidance* screen, not a return forecast or buy signal.
Stocks outside the screen are “No signal,” not predicted losers. Watchlists also
shows “Unavailable” for benchmarks, missing volatility, or metrics more than
five calendar days old.

The 35% cutoff and its five-point lift criterion were settled during exploration
of the available history. The later-date checks overlap that exploration. They
are robust retrospective evidence, not untouched future confirmation. Company
outcomes on the same dates remain
correlated; row counts should not be treated as independent statistical trials.
Adjusted price histories can also be revised after corporate actions. Continue
tracking the screen prospectively before assigning a numerical probability to a
current company or using it for alerts or trade decisions.

To reproduce the longer-history evaluation without changing `data/app.db`, make
an SQLite backup, then run the existing backfill and metric scripts against it:

```bash
.venv/bin/python - <<'PY'
import sqlite3
source = sqlite3.connect('data/app.db')
target = sqlite3.connect('/private/tmp/argus-ml-research-10y.db')
source.backup(target)
target.close()
source.close()
PY
DATABASE_URL=sqlite:////private/tmp/argus-ml-research-10y.db .venv/bin/python scripts/backfill_prices.py --period 10y
DATABASE_URL=sqlite:////private/tmp/argus-ml-research-10y.db .venv/bin/python scripts/compute_metrics.py
DATABASE_URL=sqlite:////private/tmp/argus-ml-research-10y.db .venv/bin/python scripts/validate_downside_screen.py --folds 4 --first-train-fraction 0.30
```

The validation output records both the cutoff chosen from the early training
period and the fixed cutoff used by Watchlists. They were both 0.35 in this run.
