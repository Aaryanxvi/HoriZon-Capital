# THESIS — PRELIMINARY PAGES (Roman numerals i, ii, iii …)

> Format identical to front matter. Page numbers in lowercase Roman, bottom centre.

---

## [PAGE i — CERTIFICATE]

### CERTIFICATE

This is to certify that the thesis entitled **"Horizon Capital — A Multi-Agent Autonomous Paper-Trading System with Almgren–Chriss Market-Impact Simulation"** submitted by **[STUDENT NAME]** (Roll No. [XXXX]), in partial fulfilment of the requirements for the award of the degree of Bachelor of Engineering in Electronics and Telecommunication Engineering of [University Name], is a bona fide record of the original work carried out by him/her under my supervision and guidance during the academic year 2017–18. The contents of this thesis, in full or in part, have not been submitted to any other institute or university for the award of any degree or diploma.

<br><br>

| | |
|---|---|
| **[GUIDE NAME]** | **[HOD NAME]** |
| Project Guide | Head of Department |
| Department of E&TC | Department of E&TC |

<br><br>

**[PRINCIPAL NAME]**
Principal
[College Name]

<br><br>

Place: [City]
Date: [DD-MM-YYYY]

---

## [PAGE ii — DECLARATION]

### DECLARATION

I hereby declare that the work presented in this thesis entitled **"Horizon Capital — A Multi-Agent Autonomous Paper-Trading System with Almgren–Chriss Market-Impact Simulation"** is the result of my own investigation, carried out under the supervision of **[GUIDE NAME]**, Department of Electronics and Telecommunication Engineering, [College Name].

I further declare that, to the best of my knowledge and belief, this thesis does not contain any material previously published by another person, nor any material which has been accepted for the award of any other degree or diploma of this or any other institute of higher learning, except where due acknowledgement has been made in the text. All sources of information drawn upon have been cited appropriately.

The implementation described in this report is the candidate's own and is preserved as version 0.2.0 of the Horizon Capital codebase, comprising one hundred and eighty Python source files and twenty-six thousand eight hundred and forty-five lines of code, available for inspection in the candidate's local repository.

<br><br>

**[STUDENT NAME]**
Roll No.: [XXXX]
Department of E&TC

<br>

Place: [City]
Date: [DD-MM-YYYY]

---

## [PAGE iii — ACKNOWLEDGEMENT]

### ACKNOWLEDGEMENT

The completion of any non-trivial engineering project is the result of the patient guidance, the constructive criticism, and the sustained encouragement of many individuals.

I would like to begin by expressing my deepest gratitude to my project guide, **[GUIDE NAME]**, Department of Electronics and Telecommunication Engineering, whose technical insight into asynchronous systems and whose probing questions on the soundness of the Almgren–Chriss formulation forced repeated revisions to the slippage model and produced a far stronger final design than I would have arrived at on my own.

I am sincerely thankful to **[HOD NAME]**, Head of the Department of Electronics and Telecommunication, for facilitating the institutional resources, the laboratory access, and the periodic review forums that maintained academic rigor throughout the project lifecycle.

My thanks are due also to **[PRINCIPAL NAME]**, Principal of [College Name], for the institutional environment in which inter-disciplinary work between electronics, computer science, and quantitative finance was actively encouraged.

I would like to acknowledge the open-source community whose libraries — FastAPI, SQLAlchemy, Pydantic, Rich, structlog, NumPy, pandas, yfinance, and httpx — formed the technical bedrock of this implementation. Without their stewardship the present work would not have been possible.

A special note of thanks goes to my project peers, who patiently sat through draft demonstrations, broke the system in unexpected ways, and whose stress-testing exposed several silent fail-paths in the data ingestion and stale-order cancellation subsystems.

Finally, I am profoundly grateful to my parents and family, whose unwavering support and forbearance during the long hours that this project demanded made every step of the journey possible.

<br>

**[STUDENT NAME]**

---

## [PAGE iv — LIST OF FIGURES]

### LIST OF FIGURES

| Fig. No. | Caption | Page |
|----------|---------|------|
| 3.1 | High-level system architecture of Horizon Capital | 19 |
| 3.2 | Message bus topology — publishers, subscribers, channels | 22 |
| 3.3 | Departmental hierarchy of the thirteen autonomous agents | 27 |
| 3.4 | Order lifecycle state diagram | 29 |
| 3.5 | Plot of Almgren–Chriss permanent and temporary impact versus participation rate | 31 |
| 3.6 | Multi-currency NAV reconciliation flow | 33 |
| 4.1 | End-to-end paper-trading data flow | 41 |
| 4.2 | Sequence diagram of an order from signal to fill | 44 |
| 4.3 | Risk Agent decision tree | 46 |
| 4.4 | Position Monitor mark-to-market loop | 48 |
| 4.5 | Strategy sleeve allocation pie chart | 49 |
| 4.6 | Annotated screenshot of the Rich-based Terminal Dashboard | 50 |
| 5.1 | Distribution of the three hundred and sixty-eight test cases by module | 53 |
| 5.2 | Demonstration session — equity curve over a four-hour run | 55 |
| 5.3 | Severity-bucketed gap distribution from the audit | 58 |

---

## [PAGE v — LIST OF TABLES]

### LIST OF TABLES

| Table No. | Caption | Page |
|-----------|---------|------|
| 3.1 | Module map of the `backend/app/` package | 20 |
| 3.2 | Twenty-three semantic message-type values | 23 |
| 3.3 | Twenty-eight relational tables and their key roles | 25 |
| 3.4 | Agent inventory by department | 28 |
| 3.5 | Almgren–Chriss model constants | 30 |
| 4.1 | Pinned runtime dependencies and their roles | 39 |
| 4.2 | Commission table by exchange (basis points) | 42 |
| 4.3 | Order-state transition matrix | 43 |
| 4.4 | Risk Agent thresholds and configuration parameters | 45 |
| 4.5 | Strategy sleeve allocations and refresh cadences | 49 |
| 5.1 | Quantitative code-base metrics | 53 |
| 5.2 | Forty-six identified gaps grouped by category | 57 |
| 5.3 | Production-readiness sub-scores | 60 |

---

## [PAGE vi — LIST OF ABBREVIATIONS]

### LIST OF ABBREVIATIONS

| Abbreviation | Expansion |
|--------------|-----------|
| API | Application Programming Interface |
| ASGI | Asynchronous Server Gateway Interface |
| BSE | Bombay Stock Exchange |
| CIO | Chief Investment Officer |
| CLI | Command-Line Interface |
| CVaR | Conditional Value-at-Risk |
| DB | Database |
| EOD | End of Day |
| ETC | Electronics and Telecommunication |
| FX | Foreign Exchange |
| GMM | Gaussian Mixture Model |
| GST | Goods and Services Tax |
| HRP | Hierarchical Risk Parity |
| INR | Indian Rupee |
| IT | Information Technology |
| IR | Investor Relations |
| JSON | JavaScript Object Notation |
| JWT | JSON Web Token |
| KV | Key-Value (store) |
| LLM | Large Language Model |
| LOC | Lines of Code |
| MPT | Modern Portfolio Theory |
| NAV | Net Asset Value |
| NSE | National Stock Exchange (of India) |
| OHLCV | Open-High-Low-Close-Volume |
| ORM | Object-Relational Mapper |
| P&L | Profit and Loss |
| REPL | Read-Eval-Print Loop |
| REST | Representational State Transfer |
| RSI | Relative Strength Index |
| SDE | Stochastic Differential Equation |
| SEBI | Securities and Exchange Board of India |
| SEC | Securities and Exchange Commission (USA) |
| SQL | Structured Query Language |
| STT | Securities Transaction Tax |
| TTL | Time to Live |
| TUI | Text User Interface |
| USD | United States Dollar |
| UTC | Coordinated Universal Time |
| VaR | Value-at-Risk |

---

## [PAGE vii — NOMENCLATURE]

### NOMENCLATURE

| Symbol | Description | Units |
|--------|-------------|-------|
| P | Reference market price of an instrument | currency / share |
| Q | Order quantity (shares or contracts) | shares |
| V | Average daily traded volume of the instrument | shares / day |
| σ | Daily volatility of returns | dimensionless (per day) |
| η<sub>p</sub> | Permanent-impact coefficient (Almgren–Chriss) | dimensionless |
| γ<sub>p</sub> | Permanent-impact concavity exponent | dimensionless |
| ε | Half-spread cost coefficient | dimensionless |
| η<sub>t</sub> | Temporary-impact coefficient | dimensionless |
| γ<sub>t</sub> | Temporary-impact concavity exponent | dimensionless |
| I<sub>perm</sub> | Permanent market impact | currency / share |
| I<sub>temp</sub> | Temporary market impact | currency / share |
| F | Achieved fill price | currency / share |
| C | Round-trip commission | currency |
| W | Notional value of trade ( = P × Q ) | currency |
| q<sub>old</sub>, q<sub>new</sub> | Position quantity before / after a fill | shares |
| p̄<sub>old</sub>, p̄<sub>new</sub> | Weighted-average cost basis before / after | currency / share |
| Δ<sub>R</sub> | Realised P&L change attributable to a fill | currency |
| Π<sub>U</sub> | Unrealised P&L of a held position | currency |
| Π<sub>R</sub> | Cumulative realised P&L | currency |
| N | Net Asset Value of the portfolio | USD |
| r<sub>FX</sub> | USD/INR exchange rate | dimensionless |
| L<sub>g</sub>, L<sub>n</sub> | Gross leverage, Net leverage | dimensionless |
| w<sub>i</sub> | Target weight of asset *i* in the portfolio | dimensionless (fraction) |
| α<sub>VaR</sub> | Confidence level for Value-at-Risk | dimensionless |
| τ | Stale-price rejection threshold | seconds |
| Δw<sub>min</sub> | Minimum weight delta required for re-emission | dimensionless |

---

*End of preliminary pages — Arabic page numbering begins with Chapter 1 in the next document.*
