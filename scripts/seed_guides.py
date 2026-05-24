#!/usr/bin/env python3
"""Seed betting guides into the database."""
import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

os.environ['VERCEL'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.guide import Guide

GUIDES = [
    # ── BEGINNER FOUNDATIONS ─────────────────────────────────────────────
    {
        'title': 'How to Read Betting Odds',
        'slug': 'how-to-read-betting-odds',
        'sport': None,
        'body': """## What Are Betting Odds?

Odds tell you two things at once: **how likely something is to happen** and **how much you stand to win** if it does. Before placing any bet, you need to understand how to read them.

---

## Decimal Odds (Most Common)

Decimal odds are the standard format used in Ghana and across Africa. They're the simplest to understand.

**Example:** Arsenal to win at **2.50**

- Stake GHS 10 × odds 2.50 = **GHS 25 returned** (GHS 15 profit + your GHS 10 back)

The formula is always: **Stake × Odds = Total Return**

| Odds | GHS 10 Stake Returns | Profit |
|------|----------------------|--------|
| 1.50 | GHS 15.00 | GHS 5.00 |
| 2.00 | GHS 20.00 | GHS 10.00 |
| 3.00 | GHS 30.00 | GHS 20.00 |
| 5.00 | GHS 50.00 | GHS 40.00 |
| 10.00 | GHS 100.00 | GHS 90.00 |

---

## Implied Probability

Every set of odds contains a hidden probability. You can convert any decimal odd to a percentage:

**Implied Probability = 1 ÷ Odds × 100**

- Odds of **2.00** → 1 ÷ 2.00 × 100 = **50%** chance
- Odds of **1.50** → 1 ÷ 1.50 × 100 = **67%** chance
- Odds of **4.00** → 1 ÷ 4.00 × 100 = **25%** chance

This is powerful. If you believe a team has a **60% chance** of winning but the odds imply only **45%**, that's a value bet — the bookmaker is underrating the team.

---

## The Bookmaker's Margin

Bookmakers don't offer fair odds. They build in a margin (also called the "vig" or "overround") to guarantee profit over time. For a typical football match with three outcomes:

- Home win: 2.40 → implied 41.7%
- Draw: 3.20 → implied 31.3%
- Away win: 3.00 → implied 33.3%

Total: **106.3%** — not 100%. That extra 6.3% is the bookmaker's edge.

**The key lesson:** You don't need to win every bet. You need to find odds where the true probability is higher than the implied probability.

---

## Favourite vs. Underdog

- **Low odds (1.20–1.80):** Heavy favourite, likely to win but small profit
- **Medium odds (1.80–3.00):** Fairly contested match
- **High odds (3.00+):** Underdog, unlikely to win but big payout if they do

---

## Quick Summary

1. Multiply your stake by the odds to get your total return
2. Subtract your stake to get your profit
3. Convert odds to percentages to understand implied probability
4. Look for bets where your estimated probability beats the implied probability"""
    },

    {
        'title': 'Understanding the 1X2 Market',
        'slug': 'understanding-1x2-market',
        'sport': None,
        'body': """## What Is the 1X2 Market?

The 1X2 market is the most common bet in football. You're simply predicting the result of the match:

- **1** = Home team wins
- **X** = Draw
- **2** = Away team wins

That's it. No handicaps, no conditions — just the 90-minute result (plus injury time).

---

## Why It's Called 1X2

The notation comes from old paper betting coupons where columns were labeled 1, X, and 2. It's still widely used today, especially in African and European markets.

---

## How Edi Predictions Uses 1X2

Our AI model uses the **Dixon-Coles Poisson distribution** — the same statistical model used by professional betting analysts — to calculate the probability of each scoreline. It then adds up all the ways a home win, draw, or away win can happen.

For example, a home win includes: 1-0, 2-0, 2-1, 3-0, 3-1, 3-2... and so on. The model weights each by how likely it is given both teams' attacking and defensive form.

**What drives our predictions:**
- Recent form (last 5–10 matches)
- Goals scored and conceded per game
- Home advantage factor
- Head-to-head history

---

## Reading a 1X2 Prediction

When you see a prediction card showing **Home Win — 74% confidence**, it means:

- Our model gives the home team a **74% probability** of winning
- The recommended bet is the home team
- Confidence above 70% is classified as **High**

---

## When to Back the Draw

Draws are the hardest result to predict but often the most profitable because bookmakers and casual bettors tend to undervalue them.

Signs a draw is likely:
- Two evenly matched teams (similar league position, similar form)
- Both teams with low scoring records
- High-pressure games (cup finals, relegation deciders)
- Away team with a strong defensive record

Our model flags these situations and will predict a draw when the probability justifies it.

---

## Common Mistakes

**Mistake 1: Always backing the favourite**
Big teams lose more often than people think. Man City, Real Madrid, and Barcelona all drop points regularly.

**Mistake 2: Ignoring the draw**
In top European leagues, roughly 25–30% of all matches end in draws. Ignoring this outcome costs money long-term.

**Mistake 3: Betting on too many matches**
A 5-game accumulator might look tempting, but if each match has a 70% chance of going your way, the combined probability is only 70%^5 = **16.8%**.

---

## Key Takeaway

The 1X2 market is simple but deep. Use our confidence scores to filter out uncertain predictions, and focus on matches where our model gives a clear edge over the bookmaker's implied probability."""
    },

    # ── OVER/UNDER ────────────────────────────────────────────────────────
    {
        'title': 'Over/Under Goals Explained',
        'slug': 'over-under-goals-explained',
        'sport': None,
        'body': """## What Is the Over/Under Market?

Instead of predicting who wins, you predict the **total number of goals** scored in a match. The bookmaker sets a line — most commonly **2.5** — and you bet whether the actual total goes over or under that number.

- **Over 2.5:** 3 or more goals total → you win
- **Under 2.5:** 0, 1, or 2 goals total → you win

The ".5" eliminates the possibility of a tie (there are no half goals).

---

## Common Lines

| Line | Over Means | Under Means |
|------|-----------|-------------|
| 1.5 | 2+ goals | 0 or 1 goal |
| 2.5 | 3+ goals | 0, 1, or 2 goals |
| 3.5 | 4+ goals | 0, 1, 2, or 3 goals |
| 4.5 | 5+ goals | 4 or fewer goals |

**2.5 is the most popular line** because it sits right at the average number of goals in most top football leagues (roughly 2.6–2.8 goals per game in the Premier League and La Liga).

---

## How Our Model Calculates Over/Under

We use a **Poisson distribution** to model expected goals (xG) for each team in each match. From that, we calculate the exact probability of every possible scoreline — 0-0, 1-0, 0-1, 1-1, 2-0... all the way up.

To find the probability of **Over 2.5**, we simply add up the probability of every scoreline with 3 or more total goals.

**Key inputs:**
- Team's average goals scored per game (last 10 matches)
- Team's average goals conceded per game
- Whether the match is home or away (home teams score ~15% more)
- Head-to-head historical total goals

---

## What the Confidence Score Means

A **65% confidence on Over 2.5** means our model calculates a 65% probability of 3+ goals being scored. If the bookmaker's implied probability (from the odds) is only 55%, that's a potential value bet — we think goals are more likely than the market does.

---

## Which Line to Choose?

**Use Over/Under 1.5 when:**
- You expect a high-scoring game but want more safety
- One team has an extremely poor defence
- Both teams need a win (open, attacking play expected)

**Use Over/Under 2.5 for most matches** — it's the most liquid market with the best odds.

**Use Over/Under 3.5 when:**
- Both teams have strong attacking records
- Historical H2H fixtures consistently produce 4+ goals
- The match has low tactical stakes (e.g., mid-table vs mid-table)

---

## Factors That Push Goals Higher

- Both teams averaging 1.5+ goals per game
- Both teams conceding 1.2+ goals per game
- High-scoring recent H2H meetings
- Attacking styles (high press, wing play)
- Late season with nothing to play for (or everything to play for)

## Factors That Push Goals Lower

- Both teams in strong defensive form
- Cup finals or tight derby matches
- One team parking the bus to protect a result
- Rainy or heavy pitch conditions
- Key strikers missing through injury

---

## Quick Tip

Over 1.5 hits in roughly **75–80% of top league matches**. It pays less (odds often 1.20–1.40) but it's a solid base for accumulator bets when you want reliability."""
    },

    # ── BTTS ─────────────────────────────────────────────────────────────
    {
        'title': 'Both Teams To Score (BTTS) Guide',
        'slug': 'both-teams-to-score-guide',
        'sport': None,
        'body': """## What Is BTTS?

**Both Teams To Score** — sometimes called GG (Goal-Goal) — is a bet on whether **both teams score at least one goal** in a match.

- **BTTS Yes:** Both teams score (e.g., 1-1, 2-1, 1-2, 2-2, 3-1...)
- **BTTS No:** At least one team scores zero (e.g., 1-0, 0-0, 2-0, 0-1...)

The final score doesn't matter. A 1-0 win is BTTS No. A 1-1 draw is BTTS Yes.

---

## Why BTTS Is Popular

- Simple to understand — only two outcomes
- No need to predict who wins
- Often available at close to **even money** (around 1.80–2.00 for both sides)
- Can be combined with Over/Under or match result bets

---

## How Our Model Calculates BTTS

We calculate:

1. **Home team scoring probability** = 1 − probability of home team scoring 0 goals
2. **Away team scoring probability** = 1 − probability of away team scoring 0 goals
3. **BTTS Yes probability** = Home scoring % × Away scoring %

We also blend in historical BTTS rates from our `team_stats` database — how often each team has been involved in BTTS Yes matches this season — to refine the pure Poisson estimate.

---

## Key Stats to Watch

**Favours BTTS Yes:**
- Both teams scoring in 60%+ of their matches
- Both teams conceding in most matches (poor defences)
- High-scoring leagues (Bundesliga, Serie A, Premier League)
- Derby or rivalry matches (both sides motivated to attack)

**Favours BTTS No:**
- One team keeping clean sheets regularly (50%+ of games)
- Strong favourite expected to dominate without reply
- Teams with very low average goals scored (under 1.0 per game)
- Low-stakes matches where one side may be cautious

---

## Reading the Prediction Card

On our Markets page, BTTS predictions show:

- **YES** (green): Model predicts both teams will score
- **NO** (red): Model predicts at least one clean sheet
- A percentage showing model probability for each outcome
- A probability bar showing the split

If YES shows **63%**, our model gives a 63% chance both teams find the net. At bookmaker odds of 1.85 (implied 54%), that's a meaningful edge.

---

## Combining BTTS With Other Markets

Some of the best value comes from combining BTTS with the match result:

| Combo | Means |
|-------|-------|
| Home Win + BTTS Yes | Home wins, both score (e.g., 2-1) |
| Draw + BTTS Yes | A score draw (1-1, 2-2) |
| Away Win + BTTS Yes | Away wins, both score (e.g., 1-2) |

These combos pay higher odds but require more precision. Use them when our model is confident on both components.

---

## Historical BTTS Rates by League

| League | BTTS Yes Rate |
|--------|--------------|
| Bundesliga | ~55% |
| Premier League | ~52% |
| Serie A | ~50% |
| La Liga | ~48% |
| Ligue 1 | ~46% |

If both teams are from high-BTTS leagues and both have poor defences, the probability climbs sharply."""
    },

    # ── DOUBLE CHANCE ────────────────────────────────────────────────────
    {
        'title': 'Double Chance Betting Explained',
        'slug': 'double-chance-betting-explained',
        'sport': None,
        'body': """## What Is Double Chance?

Double Chance lets you cover **two of the three possible match outcomes** with a single bet. It's a safer version of the 1X2 market.

| Option | Covers | You win if... |
|--------|--------|---------------|
| **1X** | Home Win OR Draw | Home team wins or match draws |
| **X2** | Draw OR Away Win | Match draws or away team wins |
| **12** | Home Win OR Away Win | Either team wins (no draw) |

Because you're covering two outcomes instead of one, the odds are lower — but your chance of winning is significantly higher.

---

## When to Use Each Option

### 1X — Back the Home Side Safely
Use when the home team is favoured but you're worried about a surprise draw.

*Example:* Man City vs Brentford. City should win, but Brentford could nick a point. 1X covers you for a 1-1 draw while still paying out if City win 3-0.

### X2 — Back the Away Team or Draw
Use when the away team is strong or the home team is struggling. Covers you against a home win.

*Example:* West Ham (struggling) vs Arsenal (strong away form). X2 covers Arsenal win or a draw.

### 12 — Back Either Team to Win
Use when you expect an attacking, decisive match but can't pick the winner. Common in cup ties or matches with must-win motivation for both sides.

*Example:* A playoff match where both teams need to win — a draw is almost impossible mentally.

---

## How Odds Are Calculated

Double Chance odds are derived from the 1X2 market. Our model calculates fair probabilities then adds back a small bookmaker margin:

**1X probability** = Home Win probability + Draw probability

If Home Win = 50%, Draw = 25%:
- 1X probability = 75% → odds ≈ 1.33
- X2 probability = 50% → odds ≈ 2.00
- 12 probability = 65% → odds ≈ 1.54

---

## Double Chance vs. 1X2

| Factor | 1X2 | Double Chance |
|--------|-----|---------------|
| Risk | Higher | Lower |
| Potential return | Higher | Lower |
| Outcomes covered | 1 of 3 | 2 of 3 |
| Best for | Confident picks | Reducing risk |

---

## Double Chance in Accumulators

Double Chance is excellent in accumulators where you need reliability. One uncertain selection can kill an entire acca. Replacing a risky 1X2 pick with a 1X or X2 reduces odds slightly but dramatically improves your chance of hitting all legs.

**Example acca:**
- Arsenal to win (2.10) → Arsenal 1X (1.40) — lower odds but safer
- Liverpool to win (1.80) → Liverpool 1X (1.25)

The reduced odds are worth it if it means your accumulator has a genuine 50%+ chance of landing.

---

## Confidence Score Interpretation

On edi predictions, the recommended Double Chance option shows the probability our model assigns. A **78% confidence on 12** means our model gives an 78% chance the match won't end in a draw — strong enough to consider seriously, especially if bookmaker implied probability is lower than 78%."""
    },

    # ── CORNERS ──────────────────────────────────────────────────────────
    {
        'title': 'Corners Betting: A Complete Guide',
        'slug': 'corners-betting-guide',
        'sport': None,
        'body': """## What Is Corners Betting?

Instead of betting on goals, you bet on the **total number of corner kicks** awarded in a match. Bookmakers set a line — typically **9.5 or 10.5** — and you bet over or under.

- **Over 9.5:** 10 or more corners → you win
- **Under 9.5:** 9 or fewer corners → you win

Corners betting is popular because it's less influenced by luck (a deflected goal doesn't affect corners) and more driven by tactical patterns.

---

## Common Lines

| Line | Over Means | Under Means |
|------|-----------|-------------|
| 8.5 | 9+ corners | 8 or fewer |
| 9.5 | 10+ corners | 9 or fewer |
| 10.5 | 11+ corners | 10 or fewer |
| 11.5 | 12+ corners | 11 or fewer |

Average corners in Premier League matches: **~10–11 per game**. In more defensive leagues it drops to 8–9.

---

## How Our Model Calculates Corners

We use each team's historical corner averages:

- **Avg corners won per game** (attacking pressure = more corners)
- **Avg corners conceded per game** (teams that defend deep give away corners)

We blend both teams' figures to produce an expected total, then calculate the probability of going over or under the line.

**High-corner teams:** Teams that dominate possession and attack from wide areas (Chelsea, Bayern Munich, PSG).

**Low-corner teams:** Teams that sit deep and play on the counter — they rarely win corners themselves and opponents don't need them either.

---

## Factors That Increase Corners

- **Wide attackers** who cut inside and force corners
- **Aerial threat** — teams that pump crosses generate corners when saved
- **Set-piece specialists** who recycle possession through corner routines
- **Big favourites** who dominate play and spend long periods in attacking third
- **Matches where a team desperately needs a goal** (chasing the game, late pressure)

## Factors That Decrease Corners

- **Counter-attacking teams** who score quickly and sit back
- **Low-scoring, tight matches** between defensive sides
- **Matches where one team parks the bus early** after going ahead
- **Poor pitch or weather conditions** affecting wide play

---

## Lines to Use

**Over 8.5** — Safest bet, hits in roughly 70–75% of top-league matches. Lower odds but reliable for accumulators.

**Over 9.5** — The sweet spot. Hits ~55–60% of the time in attacking leagues. Best balance of probability and return.

**Over 10.5** — Higher risk. Use only when both teams have strong corner statistics and the match setup suggests open, attacking play.

**Under 8.5 or Under 9.5** — Use when both teams are defensively solid or when you expect a low-possession, cautious match.

---

## Corners in Combination Bets

You can combine corners with goals markets:

- **Over 2.5 Goals + Over 9.5 Corners:** Attacking game from start to finish
- **Under 2.5 Goals + Over 9.5 Corners:** Defensive battle but lots of set-piece pressure
- **BTTS Yes + Over 9.5 Corners:** Both teams pushing forward and creating pressure

These combinations often offer better value than either market alone.

---

## Reading the Prediction Card

Our corners prediction shows:
- **Over** (blue) or **Under** (amber) as the recommended pick
- The specific line (8.5, 9.5, 10.5, 11.5)
- A confidence percentage and probability bar

Focus on predictions with 60%+ confidence — these represent matches where our model has clear conviction based on both teams' corner patterns."""
    },

    # ── HT/FT ────────────────────────────────────────────────────────────
    {
        'title': 'Half-Time / Full-Time Betting Guide',
        'slug': 'half-time-full-time-betting-guide',
        'sport': None,
        'body': """## What Is HT/FT?

Half-Time/Full-Time (HT/FT) is a combined bet where you predict **both the half-time result AND the full-time result**. There are 9 possible combinations:

| HT/FT | Meaning |
|-------|---------|
| H/H | Home leading at half-time, home wins full-time |
| H/D | Home leading at half-time, match draws |
| H/A | Home leading at half-time, away wins |
| D/H | Draw at half-time, home wins |
| D/D | Draw at half-time, match draws |
| D/A | Draw at half-time, away wins |
| A/H | Away leading at half-time, home wins |
| A/D | Away leading at half-time, match draws |
| A/A | Away leading at half-time, away wins |

Because you're predicting two outcomes, odds are significantly higher than a simple 1X2 bet. Odds of 3.00–8.00 are common even for the most likely combinations.

---

## The Most Common HT/FT Combinations

In top football leagues, roughly:

| Combo | Frequency |
|-------|-----------|
| H/H | ~30% of matches |
| D/H | ~18% of matches |
| D/D | ~15% of matches |
| A/A | ~12% of matches |
| D/A | ~10% of matches |

H/H is the single most common result — if you pick a match with a strong home favourite, H/H often pays 2.50–3.50 with reasonable probability.

---

## How Our Model Predicts HT/FT

We calculate the probability of every scoreline at half-time (0-0, 1-0, 0-1, 1-1, 2-0, 0-2...) and at full-time. By combining these, we derive probabilities for all 9 HT/FT combinations.

Key inputs:
- First-half scoring rates (some teams score early, others start slow)
- Second-half patterns (teams that come from behind, teams that fade)
- HT lead rate from our team_stats database
- Overall match prediction from our Poisson model

---

## When HT/FT Offers Value

**H/H (High confidence home favourite):**
Strong home teams tend to lead at half-time and hold on. Look for home teams averaging 1.5+ HT leads per 5 games.

**D/H (Home team that starts slowly):**
Some teams are notoriously slow starters but dominate the second half. If the pre-match model strongly favours the home side, D/H can pay 4.00–6.00 with genuine probability.

**A/A (Strong away side):**
Big clubs visiting smaller teams often lead at half-time and control the second half. When our model shows a >55% away win probability, A/A is worth considering.

---

## Combination Betting Tips

**Pick H/H when:**
- Our model gives 65%+ home win probability
- Home team has a strong HT lead rate (>50%)
- Away team struggles in the first half

**Consider D/H when:**
- Our model gives 60%+ home win probability but the away team is defensively solid
- Home team is known for second-half dominance
- Odds on D/H are 4.50+ (provides value even at ~20% probability)

**Avoid H/A and A/H:**
These "turnaround" outcomes are very rare (2–4% each). Unless you're doing speculative longshot betting, skip them.

---

## Risk Management

HT/FT bets are inherently unpredictable. Even a 35% probability combination will fail 65% of the time. To use HT/FT responsibly:

- **Never bet more than 2-3% of your bankroll** on a single HT/FT prediction
- Use it as a standalone bet, not within a large accumulator
- Focus on the top 2–3 combinations our model identifies, not all 9
- Look for odds that imply lower probability than our model suggests (value)"""
    },

    # ── VALUE BETS ───────────────────────────────────────────────────────
    {
        'title': 'What Is a Value Bet?',
        'slug': 'what-is-a-value-bet',
        'sport': None,
        'body': """## The Core Concept

A **value bet** is not simply a bet you think will win. It's a bet where the **odds offered by the bookmaker are higher than the true probability** of the event occurring.

This distinction is everything. Professional bettors don't ask "will this team win?" They ask "are the odds on this team generous compared to their actual chance of winning?"

---

## A Simple Example

**Chelsea vs. Wolves**

Our model calculates: Chelsea has a **65% chance** of winning.

Bookmaker A offers Chelsea at **1.65** → implied probability = 1 ÷ 1.65 = **60.6%**

That's a value bet. Our model says 65% but the bookmaker is pricing it at 60.6%. Over hundreds of bets, this edge compounds into consistent profit.

**If the bookmaker offers 1.45** → implied probability = **69%**

That's NOT a value bet. The bookmaker is pricing Chelsea higher than our model's assessment.

---

## How Edi Predictions Identifies Value Bets

Our system does this automatically:

1. The prediction engine calculates a **model probability** for each outcome
2. We fetch real bookmaker odds for the same fixture
3. We convert those odds to an **implied probability**
4. If **model probability − implied probability > 5%**, we flag it as a **value bet**

The 5% threshold filters out noise — minor differences could be modelling error. We only flag genuine edges.

---

## The Value Edge Metric

On our Value Bets tab, you'll see a number like **+8.3% edge**. This means:

- Our model gives the outcome a **61.3%** probability
- The best available bookmaker odds imply only **53.0%** probability
- The edge is **61.3% − 53.0% = 8.3%**

The higher the edge, the stronger the value signal.

---

## Why You Can Still Lose Value Bets

This is crucial to understand. A 65% probability bet loses **35% of the time**. That's not bad luck — it's expected. You might lose 3 or 4 in a row and still be making theoretically correct decisions.

Value betting is a **long-run strategy**. Over 50, 100, or 500 bets, positive expected value should result in profit. Short-term variance is unavoidable.

---

## Expected Value (EV)

The mathematical way to think about bets:

**EV = (Probability of Winning × Profit) − (Probability of Losing × Stake)**

*Example:* You bet GHS 100 at odds of 2.20 on an outcome our model says has 55% probability.

- Win: 55% × GHS 120 profit = +GHS 66
- Lose: 45% × GHS 100 stake = −GHS 45
- **EV = +GHS 21** per bet (positive — bet this)

If EV is negative, the bet is not worth taking regardless of how confident you feel.

---

## Bankroll Management With Value Bets

Even with an edge, poor bankroll management can ruin you. The **Kelly Criterion** is the mathematically optimal approach:

**Bet Size = (Edge ÷ (Odds − 1)) × Bankroll**

*Example:* Edge = 8%, Odds = 2.00, Bankroll = GHS 1,000

Bet = (0.08 ÷ 1.00) × 1,000 = **GHS 80**

In practice, many professionals use **half-Kelly** (bet half the suggested amount) to reduce variance while still capturing the edge.

---

## The Compound Effect

If you consistently bet with a 5% edge, staking 3% of your bankroll per bet:

| Bets | Starting Bankroll | Ending Bankroll |
|------|------------------|-----------------|
| 50 | GHS 1,000 | ~GHS 1,200 |
| 100 | GHS 1,000 | ~GHS 1,440 |
| 500 | GHS 1,000 | ~GHS 5,200 |

This is why professional bettors care more about edge than about picking winners."""
    },

    # ── ACCUMULATOR / MULTI ──────────────────────────────────────────────
    {
        'title': 'How to Build a Smart Accumulator',
        'slug': 'how-to-build-smart-accumulator',
        'sport': None,
        'body': """## What Is an Accumulator?

An **accumulator** (also called a parlay, multi, or combo) combines multiple selections into one bet. All selections must win for the bet to pay out. In return, the odds of each selection multiply together — meaning small stakes can return very large amounts.

**Example: 4-team accumulator**
- Team A to win: 1.80
- Team B to win: 1.60
- Over 2.5 goals: 1.90
- BTTS Yes: 1.85

Combined odds: 1.80 × 1.60 × 1.90 × 1.85 = **10.15**

GHS 10 stake → GHS 101.50 return (GHS 91.50 profit)

---

## The Mathematics of Accumulators

The more legs you add, the more your probability collapses — even with high-confidence picks.

| Legs | Each at 70% | Combined Probability |
|------|-------------|---------------------|
| 2 | 70% each | 49% |
| 3 | 70% each | 34% |
| 4 | 70% each | 24% |
| 5 | 70% each | 17% |
| 6 | 70% each | 12% |

This is why bookmakers love accumulators. They're profitable for bettors only when selections are well-researched and genuinely high-probability.

---

## Smart Accumulator Strategy

### 1. Stick to 3–5 Legs
More than 5 selections turns a calculated bet into a lottery. 3–4 legs is the sweet spot where returns are still attractive but probability is manageable.

### 2. Use High-Confidence Picks Only
Only include selections where our model shows **65% confidence or higher**. Never pad an accumulator with a guess just to boost the odds.

### 3. Mix Markets Strategically
Don't put 5 match results in one acca. Mix markets to reduce correlation:
- 2 × match results
- 1 × Over/Under
- 1 × BTTS

If all 5 matches are from the same round and the weather is bad everywhere, correlated outcomes can hurt you.

### 4. Avoid Heavily Correlated Picks
Picking "Man City win + Over 3.5 goals" in the same match is allowed but be aware — if City win 1-0, you lose both legs at once. However, picking non-correlated cross-match combinations makes statistical sense.

### 5. Use Double Chance for Uncertain Legs
If one selection makes you nervous, replace the 1X2 pick with a Double Chance. Lower odds, but it keeps your accumulator alive.

---

## Accumulator Return Calculator

| Odds | 2 legs | 3 legs | 4 legs | 5 legs |
|------|--------|--------|--------|--------|
| All at 1.80 | 3.24 | 5.83 | 10.50 | 18.90 |
| All at 2.00 | 4.00 | 8.00 | 16.00 | 32.00 |
| All at 2.50 | 6.25 | 15.63 | 39.06 | 97.66 |

---

## Managing Accumulator Variance

Even well-built accumulators lose frequently. With a 4-leg acca at 70% per selection, you'll hit roughly 1 in 4. That means 3 losing tickets for every winner.

**Practical rules:**
- Never stake more than 1–2% of your bankroll on a single accumulator
- Keep a record of every acca — profit/loss, which legs failed
- Review patterns: Are you consistently losing on one market type?

---

## Using Edi Predictions for Accumulators

The Markets page shows all our predictions sorted by confidence score. A good accumulator building process:

1. Filter by **High confidence (70%+)**
2. Pick 3–4 matches across different leagues
3. Check for fixture congestion or injury news
4. Verify the odds are not too short (minimum 1.40 per leg)
5. Calculate the combined probability before placing"""
    },

    # ── BANKROLL ─────────────────────────────────────────────────────────
    {
        'title': 'Bankroll Management: The Foundation of Profitable Betting',
        'slug': 'bankroll-management-guide',
        'sport': None,
        'body': """## Why Bankroll Management Matters More Than Picking Winners

You can have a 60% win rate and still go broke if you bet recklessly. Bankroll management is the difference between a bettor who profits long-term and one who gets wiped out by a bad run.

---

## What Is a Bankroll?

Your **bankroll** is the money you've set aside specifically for betting — money you can afford to lose without it affecting your life. This is rule zero: **never bet with money you need**.

Set a fixed starting amount. Never add to it impulsively after losses.

---

## The Flat Staking Method (Recommended for Beginners)

Bet the same fixed amount on every selection — typically **1–3% of your total bankroll**.

**Example:** GHS 1,000 bankroll, 2% stakes = GHS 20 per bet

**Why it works:**
- Protects you during losing runs
- Keeps emotions out of stake sizing
- Simple to follow

Even with a 50% win rate at average odds of 2.10, flat staking produces steady growth over time.

---

## The Percentage Staking Method

Instead of a fixed amount, bet a fixed **percentage** of your current bankroll. As your bankroll grows, bets get larger. As it shrinks, bets get smaller — protecting you automatically.

**Starting bankroll:** GHS 1,000, 2% staking

| After... | Bankroll | Stake |
|----------|----------|-------|
| Start | GHS 1,000 | GHS 20 |
| +20% profit | GHS 1,200 | GHS 24 |
| −15% drawdown | GHS 1,020 | GHS 20.40 |

This method naturally scales your bets with your success.

---

## The Kelly Criterion (Advanced)

The Kelly Criterion calculates the mathematically optimal bet size based on your edge:

**Kelly % = (Edge) ÷ (Odds − 1)**

Where **Edge = Model Probability − Implied Probability**

*Example:* Model says 60%, bookmaker implies 50%, odds = 2.00:
- Edge = 0.60 − 0.50 = 0.10 (10%)
- Kelly % = 0.10 ÷ (2.00 − 1) = 10% of bankroll

Most professionals use **fractional Kelly** (25–50% of Kelly) to reduce variance:
- Quarter Kelly: 2.5% of bankroll
- Half Kelly: 5% of bankroll

---

## Drawdowns: What to Expect

Even with a genuine edge, losing runs happen. The table below shows realistic worst-case drawdowns:

| Win Rate | Avg Odds | Expected Max Drawdown (100 bets) |
|----------|----------|-----------------------------------|
| 55% | 2.00 | 10–15 bets in a row lost |
| 60% | 2.00 | 8–12 bets |
| 65% | 1.80 | 6–9 bets |

If you're staking 2% per bet, a 10-bet losing run costs 20% of your bankroll. That's painful but survivable — and why keeping stakes small matters.

---

## Setting Limits

**Before you start betting, decide:**

1. **Session limit:** Maximum loss per day/session before you stop
2. **Weekly limit:** Maximum total loss per week
3. **Stop-loss:** If your bankroll drops 30–40%, stop completely, review, restart

These limits prevent the single biggest cause of betting losses: **chasing losses** after a bad run.

---

## Tracking Your Bets

You cannot improve what you don't measure. Keep a record of every bet:

| Date | Match | Market | Odds | Stake | Result | P/L |
|------|-------|--------|------|-------|--------|-----|

After 50–100 bets, you'll see:
- Which markets are most profitable for you
- Which leagues or teams you consistently misjudge
- Your actual ROI vs. what you expected

---

## Summary

| Rule | Why |
|------|-----|
| 1–3% per bet | Survive losing runs |
| Separate bankroll | Keep emotions out |
| Record every bet | Find and fix weaknesses |
| Never chase losses | Emotional bets lose |
| Review monthly | Continuous improvement |"""
    },

    # ── FORM & STATS ─────────────────────────────────────────────────────
    {
        'title': 'How to Use Form and Statistics in Betting',
        'slug': 'using-form-and-statistics',
        'sport': None,
        'body': """## Why Statistics Beat Gut Feeling

Human intuition is biased. We remember big wins more than small losses, overweight recent results, and are influenced by team reputations. Statistics cut through all of that.

This doesn't mean ignoring the eye test entirely — but it means grounding every decision in data.

---

## Team Form: The Last 5 Games

**Recent form** (last 5 matches) is the most important short-term indicator. A team's current momentum — injuries, confidence, tactical shape — is better reflected in the last month than the last year.

**How to read form:**

| Form | Meaning |
|------|---------|
| WWWWW | Excellent — in form, confident |
| WWWDD | Good — strong but not unstoppable |
| WDLDW | Mixed — unpredictable |
| DLLLD | Poor — struggling |
| LLLLL | Crisis — avoid backing them |

**Key caveat:** Check the opposition quality. 5 wins against bottom-half teams is less impressive than 3 wins against top-half opposition.

---

## Goals Scored and Conceded

**Average goals scored per game** tells you about attacking output.
**Average goals conceded per game** tells you about defensive solidity.

| Avg Goals Scored | Rating |
|-----------------|--------|
| 2.0+ | High attack |
| 1.5–1.9 | Good attack |
| 1.0–1.4 | Average |
| Under 1.0 | Weak attack |

**For Over/Under betting**, combine both teams:
- Home team scores 1.8, concedes 1.2
- Away team scores 1.4, concedes 1.5
- Expected total ≈ (1.8 + 1.5) + (1.4 + 1.2) ÷ 2 = rough guide to O/U line

---

## Home vs. Away Form

A team's overall record can hide massive home/away splits. Always check:

- **Home form**: Some teams are fortress at home (winning 70%+) but average away
- **Away form**: Some teams travel well; others collapse on the road

In top leagues, home teams win roughly **45%** of matches, draws account for **25%**, and away wins **30%**. But specific teams deviate significantly from these averages.

---

## Head-to-Head Records

H2H history matters most when:
- The same teams meet repeatedly in the same context (same manager, similar squad)
- There's a strong psychological edge (e.g., a team that never beats a specific opponent)
- Derby/rivalry matches with historical patterns

H2H matters less when:
- Squads have completely changed
- The psychological edge has been broken (one team finally won after a long drought)
- More than 3–4 years have passed

---

## Clean Sheet and Scoring Rate

**Clean sheet rate** = % of games a team keeps a clean sheet (useful for BTTS No)
**Scoring rate** = % of games a team scores at least once (useful for BTTS Yes)

Example:
- Team A scoring rate: 85%, clean sheet rate: 40%
- Team B scoring rate: 70%, clean sheet rate: 35%

BTTS Yes probability ≈ Team A scores (85%) × Team B scores (70%) = **59.5%**

---

## What Edi Predictions Shows You

On each prediction card and match page, you can see:
- Recent form for both teams
- Goals scored/conceded averages
- BTTS percentage over the season
- Over 2.5 percentage over the season
- Head-to-head record

These statistics directly feed into our AI model. When you see a prediction, the stats behind it are already baked in — but understanding them helps you validate or question the model's output.

---

## Combining Stats With Context

Statistics alone aren't enough. Always layer in:

- **Team news:** Missing striker? Suspended centre-back? Key player returning?
- **Fixture congestion:** Playing Thursday in Europe before Sunday league match?
- **Motivation:** End of season, relegation battle, cup final hangover?
- **Weather:** Heavy rain reduces goals and corners in outdoor stadiums

A team with excellent stats but 3 key players missing is not the same team the numbers describe."""
    },

    # ── FOOTBALL-SPECIFIC ────────────────────────────────────────────────
    {
        'title': 'Football Betting: Markets and Strategy',
        'slug': 'football-betting-markets-strategy',
        'sport': 'football',
        'body': """## Why Football Dominates Sports Betting

Football is the world's most bet sport for good reason: it's global, data-rich, and produces hundreds of markets per match. Understanding which markets offer the best value is the foundation of a profitable football betting strategy.

---

## The Main Football Markets

### Match Result (1X2)
The simplest and most popular market. Home win, draw, or away win. Best used with our 1X2 predictions when confidence is 65%+.

### Over/Under Goals
Predict total goals scored. Our model is specifically tuned for this — the Poisson distribution is the gold standard for goals prediction.

### Both Teams to Score
Two outcomes, even odds (roughly). Best when both teams have attacking records and leaky defences.

### Asian Handicap
One team receives a virtual head start (e.g., -1.5 or +0.5 goals). Eliminates the draw. More efficient market, harder to find value in.

### Double Chance
Covers two of three outcomes. Essential for accumulators when you want to back a favourite safely.

### First Goalscorer / Anytime Scorer
Highly unpredictable. Fun but not recommended for data-driven strategies — too much variance.

---

## League Characteristics

| League | Style | Avg Goals | BTTS Rate |
|--------|-------|-----------|-----------|
| Premier League | Physical, end-to-end | 2.8 | 52% |
| Bundesliga | Fast, aggressive | 3.1 | 56% |
| Serie A | Tactical, defensive | 2.6 | 48% |
| La Liga | Technical, possession | 2.7 | 50% |
| Ligue 1 | Varied | 2.5 | 46% |
| Eredivisie | Open, attacking | 3.2 | 58% |

Bundesliga and Eredivisie are the best leagues for Over goals. Serie A and Ligue 1 favour Under and clean sheet markets.

---

## Home Advantage in Football

Home advantage is real and quantifiable. Across top European leagues:
- Home teams win ~45% of matches
- Away teams win ~30%
- Draws account for ~25%

Home advantage comes from: crowd support, no travel fatigue, familiarity with the pitch, referee unconscious bias.

**However:** Home advantage has been declining since 2020. Post-COVID empty stadium football showed home teams won at similar rates to away teams. The effect is smaller now than it was in the 2000s.

---

## Injury and Team News: Non-Negotiable

Never bet without checking team news. Our predictions are based on squad stats — they don't know if a key player was injured in training this morning.

**High-impact absences:**
- First-choice striker: reduces goals scored probability by 15–25%
- Starting goalkeeper: increases goals conceded probability
- Centre-back pairing: directly affects clean sheet and Over/Under
- Key playmaker (assists leader): affects attacking fluency

Always check the official club social media or a reliable news source 1–2 hours before kickoff.

---

## Cup Competitions vs. League

**Cup matches** behave differently:
- Teams often rotate squads — stars rest for the league
- Underdogs are more motivated (one-off chance)
- Less predictable from a statistical standpoint

Our predictions work best in league football where form, squad consistency, and league position are stable signals. In cup matches, treat all predictions with more caution and reduce stakes accordingly.

---

## Live Betting Strategy

While edi predictions focuses on pre-match analysis, here are principles for live betting:

- First 15 minutes: wait for the game's tempo to be established before betting
- A team reduced to 10 men: dramatic shift in expected goals and result
- 0-0 at half-time: Over 2.5 FT becomes much less likely; Under 2.5 becomes attractive
- A team pressing desperately in the 80th+ minute: corners and BTTS opportunities increase"""
    },

    # ── BASKETBALL ───────────────────────────────────────────────────────
    {
        'title': 'Basketball Betting: NBA Markets Explained',
        'slug': 'basketball-betting-nba-guide',
        'sport': 'basketball',
        'body': """## Basketball Betting vs. Football Betting

Basketball betting is fundamentally different from football. With 100+ points per game and no draws, the markets are structured differently and the statistical analysis requires different tools.

---

## The Main Basketball Markets

### Moneyline (Win/Loss)
Simply pick which team wins. No draws in basketball — just home or away winner. Odds are closer when teams are evenly matched.

### Point Spread
The most popular NBA market. The favourite gives points, the underdog receives them.

*Example:* Lakers −5.5 vs. Celtics +5.5

- Lakers win by 6+: Lakers spread wins
- Lakers win by 5 or fewer, or Celtics win: Celtics spread wins

The spread eliminates lopsided matchups and creates a roughly 50/50 proposition.

### Over/Under (Totals)
Similar to football, but lines are set around 215–235 total points for NBA. High-scoring teams push this up; defensive teams push it down.

### Quarter and Half Betting
Bet on just the first quarter, first half, or specific periods. Useful when you expect one team to dominate early but have concerns about the full game.

---

## Key Factors in NBA Betting

### Back-to-Back Games
Teams playing the second night of back-to-backs perform significantly worse — especially on the road. This is one of the most exploitable inefficiencies in NBA betting.

*Look for:* Away team on back-to-back vs. rested home team → favour the home team and consider Over (tired defences concede more).

### Home Court Advantage
NBA home court advantage is about 3–4 points. Teams win roughly 58–60% at home across the league, but certain arenas (like Golden State or Memphis) have stronger advantages than others.

### Pace of Play
Fast-paced teams (high possessions per game) produce more points. When two fast-paced teams meet, the total shoots up. When a slow team meets a fast team, the pace usually slows down.

**High-pace teams:** Oklahoma City, Atlanta, Sacramento
**Low-pace teams (defensive):** Miami, New York, Memphis

### Three-Point Shooting Variance
Three-point shooting introduces significant game-to-game variance. A team that shoots 37% from three over a season might go 5/30 one night and 15/30 the next. This makes predicting individual game outcomes harder than season-long trends suggest.

---

## Point Spread Strategy

The spread is set by oddsmakers to attract equal action on both sides. To beat it consistently, you need to find where the market is wrong.

**Look for:**
- Home underdogs: historically outperform their spread more than road underdogs
- Teams on revenge missions (lost badly to same opponent recently)
- Division games: familiarity reduces big upsets
- Rested teams vs. fatigued opponents (back-to-backs, long road trips)

---

## Totals (Over/Under) in Basketball

NBA totals are set at around 220–230 for most games. Key factors:

**Push towards Over:**
- Both teams ranked top 10 in offensive efficiency
- Fast pace matchup
- Neither team has strong interior defence
- Injury to a key defender (not a scorer)

**Push towards Under:**
- Elite defensive team (Denver, Miami style)
- Slow pace matchup
- Back-to-back game (tired players take fewer shots)
- Cold shooting streaks (regression to mean expected)

---

## Prop Betting

Player props (points, rebounds, assists lines) are popular in basketball. While edi predictions focuses on game-level markets, here's the principle:

- **Points props:** Check minutes played history and recent scoring form
- **Rebound props:** Check matchup (big vs. big, rebounding rate)
- **Assists props:** Check if primary ball-handler or secondary role

Props offer value when a player's recent form significantly diverges from their season average in a predictable direction.

---

## Managing Basketball Variance

Basketball has more variance than football per game. Even a 65% win probability game loses 35% of the time. With multiple NBA games daily, the temptation to over-bet is high.

**Rules:**
- Stick to 1–2% stakes per game
- Treat each game independently — don't chase losses from earlier in the day
- Focus on your strongest edges, not volume"""
    },

    # ── RESPONSIBLE GAMBLING ─────────────────────────────────────────────
    {
        'title': 'Responsible Gambling: Staying in Control',
        'slug': 'responsible-gambling-guide',
        'sport': None,
        'body': """## Betting Should Be Entertainment First

Edi Predictions provides analysis and insights to help you make more informed decisions — but betting should always be treated as entertainment, not a primary income source. Understanding the risks and betting responsibly protects you and keeps the experience enjoyable.

---

## The Reality of Sports Betting

**The house always has an edge.** Even with excellent analysis, most bettors lose money over the long run. The bookmaker's margin, variance, and the difficulty of consistently outperforming the market means that profitable betting requires extreme discipline, patience, and skill.

This doesn't mean you can't enjoy betting or occasionally profit — it means going in with realistic expectations.

---

## Warning Signs of Problem Gambling

Be honest with yourself. These are signs that betting is becoming harmful:

- **Chasing losses:** Increasing stakes to recover money already lost
- **Betting with money you need:** Rent, bills, food — any essential expense
- **Hiding your betting:** Lying to family or friends about how much you bet
- **Mood driven by results:** Feeling devastated by losses, unable to think about other things
- **Inability to stop:** Deciding to stop but returning within days
- **Borrowing to bet:** Taking loans or using credit to fund gambling
- **Neglecting responsibilities:** Work, family, or personal commitments suffering

If any of these sound familiar, please speak to someone you trust or contact a support service.

---

## Setting Limits Before You Bet

The single most effective protection against problem gambling is **setting limits before you start**, not after a loss.

**Financial limits:**
- Decide on a fixed monthly betting budget
- When it's gone, stop — until next month
- Never treat winnings as "free money" to re-bet recklessly

**Time limits:**
- Set a maximum time per session (1–2 hours)
- Don't bet late at night or when emotional
- Take breaks — at least one week off per month

**Emotional rules:**
- Never bet when angry, stressed, or drunk
- Don't bet on your favourite team (emotional bias clouds judgement)
- Take a 24-hour cooling-off period after a significant loss

---

## Tools Available to Help

Most reputable bookmakers offer:

- **Deposit limits:** Cap how much you can deposit per day/week/month
- **Loss limits:** Automatic stop when losses reach a set amount
- **Session limits:** Timer that ends your session
- **Self-exclusion:** Block yourself from the platform for weeks, months, or permanently
- **Reality checks:** Notifications showing how long you've been playing and net win/loss

**Use these tools proactively** — not after you've already lost too much.

---

## The Gambler's Fallacy

One of the most dangerous misconceptions in betting:

> "I've lost 5 times in a row — I'm due a win."

This is false. Each bet is independent. A coin doesn't "remember" that it landed heads five times. The next bet has exactly the same probability regardless of what came before.

Similarly:
- A team on a losing streak isn't necessarily "due" a win
- A market that hasn't hit in 10 games isn't overdue
- Your luck doesn't change based on past results

---

## Support Resources

If you or someone you know needs help:

- **Gamblers Anonymous:** www.gamblersanonymous.org
- **BeGambleAware (UK):** www.begambleaware.org
- **National Problem Gambling Helpline:** 1-800-522-4700
- **Local counselling services:** Speak to your GP or a mental health professional

There is no shame in seeking help. Problem gambling is a recognised condition with effective treatments.

---

## Our Commitment

Edi Predictions is committed to responsible gambling. Our predictions are provided for informational and entertainment purposes. We encourage all users to:

- Set and stick to a personal betting budget
- Treat betting as entertainment, not investment
- Use our analysis as one input among many, not as guaranteed outcomes
- Prioritise wellbeing over profit at all times

*You are always in control. Bet responsibly.*"""
    },
]


def seed_guides():
    app = create_app()
    with app.app_context():
        from app.models.sport import Sport

        inserted = 0
        updated = 0

        for g in GUIDES:
            sport_id = None
            if g.get('sport'):
                sport = Sport.query.filter_by(name=g['sport']).first()
                if sport:
                    sport_id = sport.id

            existing = Guide.query.filter_by(slug=g['slug']).first()
            if existing:
                existing.title = g['title']
                existing.body = g['body']
                existing.sport_id = sport_id
                existing.published = True
                updated += 1
            else:
                guide = Guide(
                    title=g['title'],
                    slug=g['slug'],
                    body=g['body'],
                    sport_id=sport_id,
                    published=True
                )
                db.session.add(guide)
                inserted += 1

        db.session.commit()
        print(f'Done. Inserted: {inserted}, Updated: {updated}')
        print(f'Total guides: {Guide.query.filter_by(published=True).count()}')


if __name__ == '__main__':
    print('Seeding guides...')
    seed_guides()


