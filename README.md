# Bash Trading Bot — local paper trading

A Python CLI for recording simulated cryptocurrency trades. It uses CCXT only to fetch public prices. It does not need API keys and cannot place exchange orders. Trades are stored locally in `trades_journal.csv`.

## Install and run in WSL Ubuntu

Open Ubuntu and run these commands from the existing project folder:

```bash
cd /mnt/c/Projects/01-Active/Bash-Trading-Bot
python3 --version                     # Python 3.11 or newer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python trader.py
```

If creating the virtual environment reports that `ensurepip` is unavailable, install Ubuntu's `python3-venv` package and retry. Type `help` in the application to see commands and `exit` to leave. You can also run one command directly, for example `python trader.py dashboard` or `python trader.py price BTC/USDT binance`. Run from the project folder so the default journal path points to the same file each time.

## Example session

```text
paper> price BTC/USDT
paper> open
Exchange [binance]:
Symbol [BTC/USDT]:
Direction (LONG/SHORT) [LONG]: LONG
Leverage [10]:
Entry quote (current market price by default) [current price]:
... review the preview ...
Open this paper trade? (yes/no) [no]: yes
paper> positions
paper> dashboard
paper> close FULL_TRADE_ID
paper> history
paper> stats
paper> exit
```

Press Enter to accept a value in brackets. Use the full trade ID shown by `open` or `positions`. Paper positions require a `BASE/USDT` symbol so that position values and risk use the account's currency; `price` can look up other supported pairs. A custom entry is treated as an immediate simulated fill, not a pending order; the position is marked against the current market quote. The app rejects it if that immediate valuation leaves insufficient margin. The preview expires after 30 seconds; after confirmation, the app refreshes prices and checks margin again before saving. The simulated fill remains the entry shown in the preview. Commands needing current prices require a working public exchange connection; network or exchange errors leave the journal unchanged.

## Configuration

Set these environment variables before starting the application. Rates are fractions: `0.001` means 0.1% per execution, not 0.001%.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PAPER_EXCHANGE` | `binance` | Default public-data exchange ID. |
| `PAPER_LEVERAGE` | `10` | Default simulated leverage. |
| `PAPER_MAX_LEVERAGE` | `10` | Highest leverage accepted by the CLI, at least 1. |
| `PAPER_FEE_RATE` | `0.001` | Estimated fee rate per entry and exit. |
| `PAPER_SLIPPAGE_RATE` | `0.0005` | Adverse slippage rate per execution. |
| `PAPER_JOURNAL` | `trades_journal.csv` | Path to the account's journal. |

For example, `export PAPER_MAX_LEVERAGE=20 PAPER_LEVERAGE=10 PAPER_FEE_RATE=0.0005` changes settings for the current shell. Fee and slippage settings are recorded with each trade, so later changes do not rewrite existing positions. The account starts with $100 and has a fixed maximum estimated loss budget of $10 per trade. Each journal represents a separate account; do not change its path accidentally.

## How calculations work

- All calculations use decimal arithmetic. Entry and exit execution prices include adverse slippage. The stop is 1.5% from the simulated entry. The target is three times that price distance, or 4.5% from entry.
- Position size is the $10 risk budget divided by estimated loss per unit at the stop, including entry and exit fees and adverse exit slippage. Size is rounded down. With zero costs, a $10 loss at a 1.5% stop implies about $666.67 of exposure. Costs reduce the permitted exposure. Required margin is entry notional divided by simulated leverage; the entry fee and margin must fit, including an immediate mark-to-market check.
- The preview reports estimated all-in loss at the stop, net profit at the target, fees, price-based 3:1 ratio, and the lower net reward/risk ratio. An impossible trade is rejected rather than silently resized to a different risk budget.
- Balance starts at $100, incorporates closed net P&L, and deducts entry fees on open positions. Equity adds open positions' estimated gross P&L after exit costs to that balance. Displayed unrealized P&L includes both entry and estimated exit costs, so equity also equals initial capital plus realized and unrealized P&L. Available margin is conservatively limited by both balance and equity, less reserved margin, with a floor of zero. A margin deficit and negative equity remain visible.

**Stops and targets are reference levels only.** The program does not monitor prices in the background, automatically close positions, enforce liquidation, or guarantee a maximum loss. Prices can move past a stop, so actual loss when manually closed can exceed the displayed estimate and equity can become negative. Exchange fees, spreads, funding, precision rules and market conditions may differ from these estimates. USDT quotes are treated as dollar amounts. These are simulations, not financial advice.

## Journal and tests

The journal records each trade, execution costs, settings, timestamps, status, and P&L. It is reconstructed on restart; no separate balance file is silently reset. Writes use a temporary file and replacement, and malformed or externally changed files are rejected instead of knowingly overwritten. Keep backups of your journal and use only one running instance per journal: the change check is not a multi-process lock. The default journal is ignored by Git to reduce accidental publication of personal trading history.

Run the offline test suite with:

```bash
python -m unittest discover -s tests -v
```

Tests use mocked market data and never need live exchange availability.
