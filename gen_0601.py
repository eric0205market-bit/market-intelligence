import json, os

items = [
  {
    "id": 1,
    "cat": "ai-infra",
    "urgency": "deep",
    "source": "Irrational Analysis",
    "title": "HBM4 Fiasco: JEDEC Said 8Gbps, NVIDIA Demanded 11, All Three Vendors Failed",
    "idea": "JEDEC spec rated HBM4 at 8 Gbps/pin. NVIDIA's Rubin GPU immediately demanded 11 Gbps — a 38% reach beyond spec. All three major vendors failed qualification: SK Hynix ran 6 re-spins on TSMC N12, Micron tried using their own DRAM process node for the base die, Samsung had the easiest time with internal SRF4X logic (~TSMC N6/N7P). The root cause: parasitic bump capacitance from the TSV/micro-bump stacking architecture — not the DRAM itself. Meanwhile, 32G short-reach SerDes (already shipping in UCIe and NVLink die-to-die) runs at 4-8x HBM's pin speed on the same silicon.",
    "angle": "This is the foundational bear case for HBM as an architecture. The PHY was the wrong solution to a packaging problem. Two independent analysts (Irrational Analysis + BEP Research) arrived at the same conclusion from different angles: watch for hybrid bonding ramp timing as the short-term fix signal.",
    "tweetA": "JEDEC spec: 8 Gbps/pin for HBM4. NVIDIA's Rubin demanded 11. All three vendors — SK Hynix (6 re-spins), Samsung, Micron — failed. Meanwhile NVLink D2D SerDes ships at 32G. That's not a negotiation gap. That's an architecture indictment. $MU $NVDA",
    "tweetB": "SK Hynix: 6 re-spins trying to hit NVIDIA's HBM4 spec. Micron: tried using their DRAM process node for the base die. Samsung: easiest time. Three vendors, three different failure modes, same root cause: the bump capacitance problem is architectural, not a process yield issue.",
    "charts": {"count": 0, "hot": False, "desc": "TDR impedance trace diagrams referenced — Charts inside, worth opening"},
    "link": "https://irrationalanalysis.substack.com/p/hbm-high-bandwidth-mistake"
  },
  {
    "id": 2,
    "cat": "ai-infra",
    "urgency": "deep",
    "source": "Irrational Analysis",
    "title": "HBM Volume to Drop 90% in 7-10 Years — But DRAM Stocks Have 2-3x Left First",
    "idea": "Irrational Analysis argues HBM will be phased out — 90% drop in volume from peak — within 7-10 years, replaced by disaggregated LPDDR pools connected via optical SerDes. But the near-term trade is still bullish: DRAM stocks (MU, Samsung, SK Hynix) likely have another double or triple before the drawdown. The eventual peak-to-trough is projected at 70%+. Same memory cycle playbook, just with AI demand pulling the window forward. Hybrid bonding ramp = signal for when the cycle peaks.",
    "angle": "Two very different time horizons often get conflated. The architectural bear case is correct long-term. The cyclical trade is bullish near-term. Most investors are either too early on the bear or miss the bull. Hybrid bonding ramp = signal for when the cycle peaks.",
    "tweetA": "Irrational Analysis: DRAM stocks probably 2-3x from here, then 70%+ drawdown from peak. Not because the thesis is wrong — it's right. HBM gets phased out. But 'right in 7 years' and 'right for next 18 months' are different trades. Know which one you're in. $MU",
    "tweetB": "Rare call: structurally bearish on HBM architecture, tactically bullish on DRAM stocks. The 90% volume drop plays out over a decade. The next double plays out over the next AI capex cycle. The analyst making this call flagged the HBM4 fiasco before anyone else noticed.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://irrationalanalysis.substack.com/p/hbm-high-bandwidth-mistake"
  },
  {
    "id": 3,
    "cat": "ai-infra",
    "urgency": "watch",
    "source": "Irrational Analysis",
    "title": "Positron Startup: No HBM, Pure LPDDR5X, Claims Highest AI ASIC Memory Bandwidth",
    "idea": "Startup Positron (details under NDA) uses zero HBM — only commodity LPDDR5X — and claims the highest memory bandwidth of any AI ASIC. Irrational Analysis describes it as the only startup that solved the bandwidth problem correctly. Separately, Etched faces the same HBM limits as everyone else. MatX won't share details. The insight: commodity LPDDR5X beats exotic HBM stacking via clever architectural tricks — following the pattern of commoditization defeating complex incumbents when the incumbent has structural lock-in problems.",
    "angle": "Positron is the purest expression of the anti-HBM thesis in product form. If this ships at scale, it validates the entire architectural argument. Watch for any public info on Positron performance benchmarks — the NDA lift will be the signal.",
    "tweetA": "A startup solved the AI memory bottleneck by eliminating HBM entirely. Positron: only commodity LPDDR5X, no exotic stacking, claims highest AI ASIC memory bandwidth. Under NDA so no details yet. But when the analyst who called the HBM4 fiasco early says this is the answer — worth watching.",
    "tweetB": "The strangest thing about the AI chip race: the memory winner might not use any of the memory everyone is fighting over. Positron skips HBM entirely. LPDDR5X commodity DRAM + clever architecture = highest claimed bandwidth. Commodity beats exotic. Again.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://irrationalanalysis.substack.com/p/hbm-high-bandwidth-mistake"
  },
  {
    "id": 4,
    "cat": "ai-infra",
    "urgency": "deep",
    "source": "BEP Research",
    "title": "The Shoreline Problem: Clock-Forwarded SerDes Unifies Compute AND Disaggregates Memory — Same Physics",
    "idea": "BEP Research makes the connection most analysts miss: the clock-forwarded SerDes at the heart of NVIDIA's rack-scale NVLink (stitching compute dies into one coherent processor) is the same primitive that would let memory move 30 meters down the hall into disaggregated LPDDR pools. Same technology, opposite applications — one stitches compute, one separates memory from compute. The bear case has a soft underbelly: 5ns/meter of fiber means a 30m memory pool = ~300ns round-trip latency vs ~100ns for wall-mounted HBM. Optical is a capacity/bandwidth tier, not a hot-path latency replacement.",
    "angle": "The most nuanced HBM take in this window: the physics is settled, but the demand destruction timing is speculative. The '90% volume drop' is right IF co-packaged optical receivers get cheap enough within the investable window. Watch receiver cost per bit, not chip speed.",
    "tweetA": "The same physics that lets NVIDIA stitch compute dies into one coherent processor (clock-forwarded SerDes) also lets memory move 30 meters down the hall. One primitive. Two applications. One company positioned to own both outcomes. The link is the chip. $NVDA",
    "tweetB": "BEP Research reality check on the HBM bear case: 30 meters of fiber = 300ns round trip. HBM on the wall = 100ns. The optical memory pool is a capacity tier, not a latency replacement. The architecture is right. Whether it pays within an investment horizon is the speculative part.",
    "charts": {"count": 0, "hot": False, "desc": "Charts inside — worth opening"},
    "link": "https://bepresearch.substack.com/p/the-shoreline-problem-a-bear-case"
  },
  {
    "id": 5,
    "cat": "ai-infra",
    "urgency": "deep",
    "source": "BEP Research",
    "title": "NVIDIA Writes the Spec — Can Widen HBM Doorway (Hybrid Bonding) OR Build the Optical Pool In-House",
    "idea": "The HBM disruption thesis has a structural problem: NVIDIA sets the roadmap that memory vendors chase. Hybrid bonding (next-gen die stacking without bulky micro-bumps) may let HBM widen its own bandwidth doorway before optical becomes cost-competitive. Alternatively, NVIDIA could pull co-packaged optical in-house and own the replacement architecture. Apple did this exact move with iPhone supply chain — turned the hardest manufacturing problem into a moat. BEP conclusion: betting against HBM likely means betting against NVIDIA, and NVIDIA writes the spec.",
    "angle": "The most important constraint on any HBM disruption trade: NVIDIA is the incumbent AND the architect of whatever replaces it. The analog is Apple vertically integrating iPhone manufacturing. The supply chain got disrupted, Apple captured all the value.",
    "tweetA": "The HBM bear case has one problem: NVIDIA wrote the spec being disrupted. They can widen HBM's doorway with hybrid bonding OR pull co-packaged optical in-house. Apple did this with iPhone supply chain — the hardest manufacturing problem became the deepest moat. NVDA is doing the same with memory.",
    "tweetB": "Every AI chip disruption narrative assumes the incumbent is static. It's not. NVIDIA owns the roadmap the memory vendors chase. The architectural fix for HBM (optical disaggregation) either costs NVIDIA nothing because they ship it — or gives them a new moat because they build it first.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://bepresearch.substack.com/p/the-shoreline-problem-a-bear-case"
  },
  {
    "id": 6,
    "cat": "positioning",
    "urgency": "deep",
    "source": "TMAD Weekly / Trading Mindset and Data",
    "title": "41 Cents of Every Passive Dollar Auto-Forced Into Top 10 Mega-Caps — CTAs at Maximum Long",
    "idea": "Out of every $1 entering passive vehicles, 41 cents is mechanically forced into the top 10 mega-cap tech stocks. Combined with $852 billion in passive inflows this cycle, that represents ~$349B in non-discretionary demand for 10 names. Simultaneously, CTAs are sitting at maximum long equity exposure — no room left to buy trend, but enormous structural capacity to sell if momentum reverses. TMAD calls this a 'massive synthetic short downside gamma risk' — upside beta capped (no incremental buyers), downside beta uncapped.",
    "angle": "The mechanical bid from passive creates the trend CTAs chase; CTAs reach max long; anything that breaks the trend triggers CTA selling into a market where the mechanical buyers have already fully deployed. The setup is not bearish by itself — it is maximally asymmetric.",
    "tweetA": "41 cents of every passive dollar auto-routes to 10 stocks. $852B in passive inflows = roughly $349B in mechanical demand for mega-cap tech regardless of fundamentals. CTAs are maxed long. Upside is capped — no more incremental buyers. Downside is not. $SPX",
    "tweetB": "The passive inflow machine is a valuation distortion engine, not a market signal. $852B in, 41% auto-concentrated into 10 names, CTAs chasing the trend to maximum long. When passive stops growing, the mechanical bid stops. What happens to prices set by buyers who cannot say no?",
    "charts": {"count": 0, "hot": False, "desc": "Charts inside — worth opening"},
    "link": "https://www.tmad.news/p/tmad-weekly-options-mechanics-and"
  },
  {
    "id": 7,
    "cat": "macro",
    "urgency": "deep",
    "source": "TMAD Weekly / Trading Mindset and Data",
    "title": "Late-Cycle Melt-Up: 84% Q1 Earnings Beat Rate, Market Structurally Protected Until Specific Options Expire",
    "idea": "84% of Q1 S&P 500 companies beat earnings expectations. Combined with $852B in passive inflows, the index is grinding higher. But TMAD identifies a specific time-limited safety net: automatic trading mechanisms trap short-sellers and force algorithmic dip-buying tied to a specific options structure. Mid-June FOMC = minor pullback window with dips likely bought. Once those specific options protections expire, the safety nets disappear. The protection is NOT valuation, NOT earnings — it is a derivatives structure with a defined expiration.",
    "angle": "The mechanics matter more than the narrative here. Knowing WHEN the safety net expires matters more than debating whether the market is expensive. The options structure around June FOMC and subsequent expiries is the calendar event to watch, not the macro data.",
    "tweetA": "84% Q1 earnings beat rate. SPX 9 straight weeks up. But the market's safety net is a specific options structure, not fundamentals. TMAD maps when it expires. After the June FOMC dip-buy window closes and those protections roll off — the cushion disappears. The calendar matters more than the narrative.",
    "tweetB": "The melt-up is textbook late cycle: real but fragile. 84% earnings beats + $852B passive inflows levitate the index. CTAs max long trap shorts. Automatic dip-buying absorbs the dips. Until the options structure underlying all of it expires. Then the physics changes.",
    "charts": {"count": 0, "hot": False, "desc": "Charts inside — worth opening"},
    "link": "https://www.tmad.news/p/tmad-weekly-options-mechanics-and"
  },
  {
    "id": 8,
    "cat": "energy",
    "urgency": "watch",
    "source": "TMAD Weekly / Trading Mindset and Data",
    "title": "AI Infrastructure $869B by 2027 Straining US Power Grid — Plus Gasoline at $4.33 National Average",
    "idea": "AI infrastructure buildout is on track to hit $869 billion by 2027, straining the US power grid to a degree not seen in decades — a severe negative supply shock as energy costs escalate. Simultaneously, gasoline climbed past $4.33 national average. Global reserves depleting rapidly, insurance premiums skyrocketing (Middle East maritime risk), and refinery infrastructure under threat. Two separate supply-side energy shocks — downstream (gasoline/oil) and upstream (electricity/grid) — converging in the same cycle. Big tech is taking on massive debt for the buildout.",
    "angle": "The AI capex story and the energy constraint story are usually told separately. They're the same story: unprecedented electricity demand growth hitting an underbuilt grid, while oil market supply disruptions hit consumers at the pump. Long grid infrastructure and natural gas peakers.",
    "tweetA": "$869B projected AI infrastructure spend by 2027 is straining the US power grid to a degree not seen in decades. This is a hard physical constraint on datacenter buildout speed. Gasoline at $4.33 adds oil supply shock on top. Two energy supply shocks — electricity demand (AI) and oil supply (geopolitics) — hitting simultaneously. $VST $CEG $NRG",
    "tweetB": "AI capex gets the headlines. The power bill doesn't. $869B in AI infrastructure by 2027, US grid under decade-level strain, gasoline $4.33, Middle East refinery risk. The bottleneck is not chips. It is not bandwidth. It is kilowatts per rack.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://www.tmad.news/p/tmad-weekly-options-mechanics-and"
  },
  {
    "id": 9,
    "cat": "macro",
    "urgency": "deep",
    "source": "Neil Sethi / The Week Ahead",
    "title": "Core PCE Highest Since November 2023, Savings Rate Lowest Since June 2022",
    "idea": "April personal income growth was negative in real terms. Personal spending grew modestly but only by depleting savings — savings rate fell to its lowest since June 2022. Core PCE year-over-year was the highest since November 2023. The consumer is spending through diminishing real income and thinning savings. Kevin Warsh inherits this data as incoming Fed Chair: sticky inflation + consumer running down buffers. NFP this Friday will be the first clean data point (no shutdown distortions) in months.",
    "angle": "The consumer resilience story depends on income outpacing inflation. It is not. It depends on savings as a buffer. That buffer is thinning. The Fed cannot cut into this data — and Warsh, unlike Powell, will not pretend otherwise. Core PCE at Nov 2023 highs binds his hands from day one.",
    "tweetA": "Core PCE: highest since November 2023. Savings rate: lowest since June 2022. Real personal income: negative. The consumer is spending through depleted savings into declining real income. That is not resilience. That is running down the clock. Kevin Warsh is not going to cut into this.",
    "tweetB": "Kevin Warsh inherits: core PCE at Nov 2023 highs, savings rate at 2022 lows, real income negative. The political pressure to cut is enormous. The data makes it impossible. That tension — between what markets want and what the data allows — is the macro story for H2 2026.",
    "charts": {"count": 0, "hot": False, "desc": "DB one-pager + BoA cheat sheets referenced — Charts inside, worth opening"},
    "link": "https://neilsethi.substack.com/p/the-week-ahead-53126"
  },
  {
    "id": 10,
    "cat": "geopolitics",
    "urgency": "act-now",
    "source": "Neil Sethi / The Week Ahead",
    "title": "Iran Peace Deal Collapses on Polymarket: 80% Last Saturday → 30% Now",
    "idea": "Polymarket now prices a permanent US-Iran peace deal by June 30 at 30% — down from nearly 80% last Saturday and half of where it sat earlier in the week. The collapse reflects Trump being caught between wanting a deal and needing it to look like a victory, while Iran knows time pressure from upcoming midterms is building. Hard-line Republicans are counter-pressuring Trump to 'finish the job.' Neil Sethi: 'both sides feel they have the upper hand, and both need a conclusion which allows them to claim victory.' The Strait of Hormuz remains closed.",
    "angle": "The peace premium embedded in crude prices (Iran deal = supply coming back online) is now a risk, not a floor. 30% is still above zero — but the 50-percentage-point collapse in one week means the crude unwind that drove last week's 'everything rally' is now sitting on a false premise.",
    "tweetA": "Iran peace deal by June 30: 80% last Saturday. 30% today. That's 50 percentage points in one week. The crude peace premium was priced for certainty that no longer exists. Strait of Hormuz still closed. Trump trapped between wanting a deal and needing it to look strong.",
    "tweetB": "Polymarket Iran deal odds: 80% to 30% in 7 days. Iran knows Trump faces midterm pressure. Hard-liners are pushing him to finish the job. Neither side can claim victory on current terms. That is not a setup for June 30 resolution. The crude supply premium deserves a relook.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://neilsethi.substack.com/p/the-week-ahead-53126"
  },
  {
    "id": 11,
    "cat": "macro",
    "urgency": "deep",
    "source": "Neil Sethi / The Week Ahead",
    "title": "SPX 9th Straight Weekly Gain — Longest Streak Since 2023, Best Month Since April",
    "idea": "The S&P 500 posted its 9th consecutive weekly gain — the longest streak since 2023. May 2026 was the best monthly performance since April. Nasdaq led (+2.5% last week) followed by Russell 2000 (+1.9%), SPX (+1.4%), and DJIA (+0.9%). Fedspeak turned more hawkish during the week yet rates softened — providing fuel to equities. Q2 earnings estimates ratcheting higher. Positioning rebounded pushing to levels where most analysts think falling volatility or a new catalyst are needed to push higher. Buybacks remain solid with corporates in open windows.",
    "angle": "Nine straight weeks attracts trend-followers and repels mean-reversion shorts. The positioning signal: analysts now broadly agree the incremental buyer pool is shrinking. The streak itself becomes the risk — any break would have disproportionate impact on CTAs at max long.",
    "tweetA": "Nine straight weekly gains for the S&P 500. Longest streak since 2023. Best month since April. Fedspeak hawkish but rates fell anyway. Q2 estimates ratcheting higher. The pain trade is still higher — but the pool of incremental buyers to push it there keeps shrinking. $SPX",
    "tweetB": "SPX: 9 consecutive weekly gains. Core PCE at 2023 highs. Iran deal at 30% on Polymarket. Gasoline at $4.33. The wall of worry that bull markets climb is getting impressively tall. At some point the market has to look up at what it is climbing.",
    "charts": {"count": 0, "hot": False, "desc": "DB and BoA weekly summary cheat sheets — Charts inside, worth opening"},
    "link": "https://neilsethi.substack.com/p/the-week-ahead-53126"
  },
  {
    "id": 12,
    "cat": "tech",
    "urgency": "watch",
    "source": "Neil Sethi / The Week Ahead",
    "title": "Quantinuum (QNT) Debut Expected This Week — One of Largest Tech Offerings of the Year",
    "idea": "Honeywell-backed quantum computing company Quantinuum (QNT) is expected to debut this week as one of the largest technology offerings of the year. Also this week: Computex Taipei and Microsoft Build developer conference, both expected to feature major AI, datacenter, software, and robotics announcements. AVGO (Broadcom) reports Wednesday — the key semiconductor earnings in the Q1 wind-down. FedEx completes spinoff of FedEx Freight. Three separate AI/tech narrative catalysts in five days.",
    "angle": "Quantinuum as a large public debut forces every institutional allocator who dismissed quantum computing to put a number on it. Most institutional investors cannot explain the difference between trapped-ion and superconducting qubits — that knowledge gap is where bad IPO decisions happen.",
    "tweetA": "This week: Quantinuum IPO (one of the largest tech offerings of the year), Computex Taipei, Microsoft Build, and AVGO earnings. Four separate AI/tech narrative moments in five trading days. The market gets a story this week. Whether it likes the story is the question.",
    "tweetB": "Quantinuum debuting as one of the year's largest tech IPOs forces a moment: every institutional allocator who dismissed quantum computing now has to price it. The trapped-ion vs superconducting qubit debate aside — the price discovery this week will be instructive about where the market actually puts quantum.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://neilsethi.substack.com/p/the-week-ahead-53126"
  },
  {
    "id": 13,
    "cat": "geopolitics",
    "urgency": "act-now",
    "source": "The Pressure Point / whatsthelatest.ai",
    "title": "Colombia Election TODAY: US Anti-Cartel Architecture at Stake — 200+ Dead from US Boat Strikes, 52 in SE Colombia Clashes",
    "idea": "Colombia voted today (May 31) in a presidential election that functions as a routing decision for US anti-cartel architecture. The US has expanded its hemisphere toolkit to include kinetic interdiction, gang-terror designations, and Guantanamo-adjacent military contacts. Colombia is the missing connector: upstream of cocaine supply, downstream of US enforcement demand. Key data: 200+ deaths from US boat strikes since last year, 52 fighters killed in SE Colombia armed-group clashes this month alone. Armed groups are grabbing territory NOW before the next president resets rules of engagement. Runoff (if no 50%+1 majority): June 21.",
    "angle": "Colombia is not a niche LatAm story — it is the choke point for the US anti-cartel campaign affecting drug supply, cartel financing, and regional security from Ecuador to Panama to Guatemala. A hostile Bogota slows the entire operation without formally breaking any alliance. Watch COP and Colombian sovereign spreads.",
    "tweetA": "Colombia voted today. The question is not left vs right — it is whether the next president grants, stalls, or auctions US anti-cartel cooperation. Intelligence sharing. Extradition tempo. Interdiction permissions. 200+ dead from US boat strikes this year. Armed groups grabbing territory during the transition gap right now.",
    "tweetB": "The US can strike boats and designate gangs across the hemisphere. But Colombia controls the terrain where cocaine, armed groups, ports, and extradition pipelines intersect. A hostile Bogota does not formally break the alliance — it just makes everything slower, more expensive, and less effective. Runoff: June 21.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://pressurepoint.whatsthelatest.ai/archive/the-pressure-point-bogota-becomes-the-drug-war/"
  },
  {
    "id": 14,
    "cat": "geopolitics",
    "urgency": "deep",
    "source": "The Pressure Point / whatsthelatest.ai",
    "title": "Ecuador Pre-Positioned Before Colombia Results: Ended Levies After Meeting Conservative Candidate",
    "idea": "Ecuador's President Noboa ended Colombia trade levies after meeting with a conservative Colombian presidential candidate — before election results were certified. Not symbolism: this is pre-positioning for border security, trade friction, and counternarcotics coordination under a possible new doctrine. Regional diplomacy in LatAm is no longer waiting for electoral outcomes. Capital markets are pricing the same — investors are marking candidates by expected treatment of fiscal reform, oil and mining policy, and US security alignment. 'Executability, not ideology' is what markets are watching.",
    "angle": "The regional pre-positioning signal is often more revealing than the outcome itself. Ecuador moving before the vote tells you where the regional balance of power is heading regardless of who wins. Watch for similar moves from Panama and Guatemala as leading indicators.",
    "tweetA": "Ecuador ended Colombia trade levies before election results were certified — after meeting the conservative candidate. That is not diplomacy. That is pre-positioning. Neighboring governments are betting on the outcome and rewriting regional architecture before the vote count is done.",
    "tweetB": "Colombia election tells us about 4 years of US anti-cartel architecture. Ecuador's pre-vote move tells us about 4 years of regional trade and security geometry. Capital markets are already pricing 'executability' not ideology in Colombian bonds.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://pressurepoint.whatsthelatest.ai/archive/the-pressure-point-bogota-becomes-the-drug-war/"
  },
  {
    "id": 15,
    "cat": "macro",
    "urgency": "deep",
    "source": "Cubic Analytics",
    "title": "Nasdaq +33% From March Lows Despite Hormuz Closed, No Iran Deal, Consumer Confidence at ATLs",
    "idea": "The Nasdaq-100 has gained +33% in two months from March 2026 lows despite: no Iran peace deal, the Strait of Hormuz remaining closed, potential Cuba escalation, inflation reaccelerating, and consumer confidence making new all-time lows. Cubic Analytics' framework: the economy does not need to be GOOD for the bull market to stay intact — it needs to be 'good enough.' The rally was driven by 'less bad news in the rearview mirror than potential bad news on the road ahead' — not by resolved risks.",
    "angle": "This is the clearest articulation of why perma-bears miss rallies: they wait for clean skies. The market bottoms on 'less worse' not 'good.' Nasdaq +33% with Hormuz closed and consumer confidence at ATLs proves the framework. The question: has the catalyst set for the next leg been established?",
    "tweetA": "Nasdaq +33% from March lows. In that same period: Hormuz still closed, no Iran deal, Cuba escalation risk, inflation reaccelerating, consumer confidence at all-time lows. The market does not need the problems solved. It needs to price less bad news ahead than behind. It did.",
    "tweetB": "Perma-bear problem in one data point: $QQQ +33% in 2 months with the Strait of Hormuz closed and consumer confidence at ATLs. Cubic Analytics nails it: the economy only needs to be good ENOUGH to support the bull market. Waiting for clean skies means missing the move.",
    "charts": {"count": 0, "hot": False, "desc": "Real GDP chart vs prior recessions — Charts inside, worth opening"},
    "link": "https://cubicanalytics.substack.com/p/focus-on-this-macro-data"
  },
  {
    "id": 16,
    "cat": "macro",
    "urgency": "deep",
    "source": "Cubic Analytics",
    "title": "Real GDP Q1'26 +2.6% YoY (Accelerating from +2.0% Q4'25) + Redbook Retail +9.0% YoY",
    "idea": "Real GDP Q1'26 came in at +2.6% YoY — an acceleration from Q4'25's +2.0% YoY and far more useful than the misleading +1.6% QoQ annualized headline. Cubic Analytics argues the YoY lens is specifically better because QoQ annualized is 'a flawed metric.' Separately, Redbook same-store retail sales jumped to +9.0% YoY. The GDP trajectory looks like post-GFC expansion (2010-2019), not pre-recession patterns. Cubic conclusion: this does not look like 1990, 2001, or 2008 lead-up dynamics.",
    "angle": "The GDP framing choice matters enormously: +1.6% QoQ annualized (weak) vs +2.6% YoY accelerating (strong). Which lens you use determines your investment posture. Redbook +9.0% adds consumer data that flatly contradicts the recession setup narrative.",
    "tweetA": "Real GDP Q1'26: +1.6% QoQ annualized (weak). Or +2.6% YoY, accelerating from +2.0% in Q4. Cubic Analytics prefers the YoY lens — and it looks nothing like 1990, 2001, or 2008 pre-recession setups. Plus Redbook retail +9.0% YoY. Recession callers need to answer this data.",
    "tweetB": "Redbook same-store retail sales: +9.0% YoY. Real GDP Q1'26: +2.6% YoY, accelerating. The hard macro data is not cooperating with the recession narrative. The consumer is running down savings to generate it — but the top-line number is what the market prices. For now.",
    "charts": {"count": 0, "hot": False, "desc": "GDP YoY trajectory vs prior recessions — Charts inside, worth opening"},
    "link": "https://cubicanalytics.substack.com/p/focus-on-this-macro-data"
  },
  {
    "id": 17,
    "cat": "macro",
    "urgency": "deep",
    "source": "Neil Sethi / The Week Ahead",
    "title": "Kevin Warsh Fed Chair: Structural Non-Dovish Overhang — Last Week Before Blackout",
    "idea": "Kevin Warsh's appointment as Fed Chair introduces a decidedly non-dovish presence who views high yields as structural, not transitional. Combined with core PCE at November 2023 highs, real income negative, and the Fed Beige Book for the June meeting releasing Wednesday, the rate path is increasingly binary: no cut for longer, or a cut that validates ongoing inflation. This is the last week before the Fed blackout (last scheduled speakers: Barr, Kashkari, Hammack, Logan, Daly). Removing the 'Fed will blink' put quietly compresses equity multiples.",
    "angle": "Warsh at the Fed removes the option value embedded in equity multiples — the expectation that the Fed blinks if growth slows. That option was worth real multiple points. Its removal is a quiet compressor that does not show up in EPS estimates but shows up in P/E ratios over time.",
    "tweetA": "Kevin Warsh at the Fed is not about the next meeting. It is about the option value baked into equity multiples — the expectation that the Fed will blink. Warsh will not blink. Core PCE at Nov 2023 highs gives him the data to hold. That Fed put was worth real multiple points. It is gone.",
    "tweetB": "Last week before Fed blackout. Warsh takes the chair. Core PCE at cycle highs. Savings rate at cycle lows. The hawkish Fed scenario has moved from tail risk to base case — and equity multiples are still pricing the dovish scenario. Something has to give.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://neilsethi.substack.com/p/the-week-ahead-53126"
  },
  {
    "id": 18,
    "cat": "macro",
    "urgency": "deep",
    "source": "Eliant's Exploits",
    "title": "Everything Rally Was Iran-Progress Driven: Now Iran Deal at 30% vs 80% Last Saturday",
    "idea": "Eliant's week recap identifies the specific driver: positive Iran-deal progression eased bond volatility and triggered crude unwind to the downside — sparking the 'everything rally.' QQQ best performer (+~300bps), Dow worst but still positive (+~100bps). Now Polymarket has the deal at 30% versus 80% a week ago. If the rally was specifically bought on Iran optimism, the 50-point collapse in odds is not yet priced into crude, bond vol, or equities. The mismatch between the catalyst (Iran progress) and current probability (30%) is the setup.",
    "angle": "The Iran narrative was the specific catalyst for the week's rally — which means the Polymarket collapse is actionable: if Iran-deal optimism drove crude lower and bond vol lower, Iran-deal pessimism should reverse both. Watch crude and bond vol for the unwind tell.",
    "tweetA": "Last week's everything rally had a specific cause: Iran deal optimism. Bond vol eased. Crude unwound lower. Now Polymarket has the deal at 30% vs 80% a week ago. If the rally was bought on Iran optimism, it can be sold on Iran pessimism. Watch crude and bond vol for the tell.",
    "tweetB": "Everything rallied last week on Iran-deal hope. Now odds are 30% from 80%. The market is either right to dismiss the Polymarket signal — or there is a retrace in crude, bonds, and equities that nobody is positioned for because everyone is 9 weeks into a melt-up.",
    "charts": {"count": 0, "hot": False, "desc": "STD channel charts for SPY/QQQ/IWM/DJIA and factor/basket performance — Charts inside, worth opening"},
    "link": "https://www.eliantcapital.com/p/the-week-ahead-53126"
  },
  {
    "id": 19,
    "cat": "positioning",
    "urgency": "deep",
    "source": "Eliant's Exploits",
    "title": "Best YTD Baskets: Industrial/Auto Analog Recovery, Rebuilding US Industrial Sovereignty — NOT Just Mega-Cap AI",
    "idea": "Eliant's YTD basket performance from Plutus portfolios: top performers are Industrial and Auto Analog Recovery, Rebuilding US Industrial Sovereignty, Google Ecosystem, Next-Gen Space Economy, and Agentic Economy. Bottom performers: Global Marketplace, Gaming and Media, Make Housing Great Again. The industrial sovereignty and analog recovery themes are the year's actual rotation story — not visible in the mega-cap AI narrative that dominates coverage. Housing basket underperformance = structural message: high yields are staying, not falling.",
    "angle": "The factor leadership and basket performance tell a more interesting story than the index level: the rotation within the bull market is toward industrial sovereignty, analog recovery, and defense tech — themes that benefit from tariffs, reshoring, and constrained supply chains, not rate cuts.",
    "tweetA": "Best YTD baskets: Industrial/Auto Analog Recovery, Rebuilding US Industrial Sovereignty, Next-Gen Space Economy. The rotation story is NOT just AI mega-caps. It is analog recovery + industrial sovereignty + defense — themes that benefit from tariffs and reshoring, not rate cuts.",
    "tweetB": "Worst YTD basket: Make Housing Great Again. That is the market's honest answer about rate expectations. Housing needs cuts. The bond market is not pricing cuts. Kevin Warsh is not going to cut. The worst-performing basket is a real-time interest rate forecast.",
    "charts": {"count": 0, "hot": False, "desc": "Factor and basket performance charts — Charts inside, worth opening"},
    "link": "https://www.eliantcapital.com/p/the-week-ahead-53126"
  },
  {
    "id": 20,
    "cat": "quant",
    "urgency": "deep",
    "source": "PrincetonChen / Weekly Paper Review Wall",
    "title": "HMM + RL Regime Framework on SPY/TLT/GLD 2004-2025: Highest Sharpe with Fully Interpretable Discrete Mapping",
    "idea": "New paper (arXiv:2605.27848, published 5 days ago): 3-state Gaussian HMM on daily SPY/TLT/GLD 2004-2025 identifies low-vol, transitional, and high-vol regimes selected by BIC. RL layer learns regime-conditioned allocation. Key results: SPY dominates in stable regimes, TLT+GLD protect in stress. Both HMM allocations beat passive SPY. RL policy achieves the highest Sharpe with materially lower drawdowns AND remains fully interpretable via discrete regime-to-action mapping. One-day execution lag, 30% OOS window, no look-ahead.",
    "angle": "The interpretability claim is the key selling point: discrete regime-to-action maps are explainable to any risk committee. This is more deployable than any black-box alternative. A clean replicable template for tactical SPY/TLT/GLD rotation with 20-year validation.",
    "tweetA": "New paper: 3-state HMM + RL on SPY/TLT/GLD over 20 years. RL achieves highest Sharpe + lower drawdowns vs passive — with fully interpretable discrete regime-to-action maps. TLT+GLD protect in high-vol. SPY dominates in low-vol. Three assets. Three regimes. Fully explained.",
    "tweetB": "The dirty secret of sophisticated quant strategies: a well-calibrated HMM + simple RL across just SPY/TLT/GLD beats passive over two decades. No exotic factors. No hundreds of parameters. Three assets, three regimes, one rule per state. The complexity premium in active management does not show up here.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://arxiv.org/abs/2605.27848"
  },
  {
    "id": 21,
    "cat": "quant",
    "urgency": "deep",
    "source": "PrincetonChen / Weekly Paper Review Wall",
    "title": "Bayesian CTA Decomposition: Long-Horizon Trend Is the Sharpe Anchor, Short-Horizon Is Just Convexity",
    "idea": "Paper (arXiv:2507.15876): Bayesian graphical decomposition of CTA returns into short-term trend, long-term trend, and market-beta across equity/bond/FX/commodity futures using 20-500 day lookback-straddle factors. Key finding: the Sharpe-optimal blend tilts decisively toward the long-horizon component. Short-horizon trend is a convexity and diversification add-on, not an alpha source. Proves the lookback-straddle delta acts as a drift filter. Disentangles precisely when each horizon adds value.",
    "angle": "Most CTA allocators fire their managers during periods when short-horizon underperforms, without realizing long-horizon is the actual Sharpe source. This paper provides the analytical basis to defend CTA positions through short-horizon drawdowns — and to understand what you are actually paying for.",
    "tweetA": "Bayesian decomposition of CTA returns confirms: long-horizon trend is the Sharpe anchor. Short-horizon is convexity + diversification, not alpha. When your CTA is not working over 3 months, you are watching the convexity sleeve — while the alpha sleeve runs in the background.",
    "tweetB": "For CTA allocators: the Sharpe-optimal lookback is long-term, not short. Short-horizon trend is an add-on for convexity and diversification. If you redeem your CTA because it underperformed for a quarter, you fired the driver because the passenger had a rough flight.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://arxiv.org/abs/2507.15876"
  },
  {
    "id": 22,
    "cat": "quant",
    "urgency": "deep",
    "source": "PrincetonChen / Weekly Paper Review Wall",
    "title": "Deep Hedging Uncertainty: Moneyness (Not Vol) Drives Model Confidence — ATM Options Most Uncertain",
    "idea": "Paper (arXiv:2603.10137): ensemble-based uncertainty measurement for deep hedging in a Heston environment with proportional transaction costs. Key finding: ensemble uncertainty reliably predicts hedging performance, but the primary driver is option MONEYNESS, not implied volatility. Uncertainty-performance relationship inverts under weak leverage conditions. Practical implication: recalibrate hedging aggressiveness near ATM, not when vol spikes. ATM options have the least trustworthy neural hedge ratios — which is also where gamma exposure is highest.",
    "angle": "This inverts the intuition most options practitioners have: they check vol to decide how much to trust their models. The correct variable to watch is moneyness. ATM options are where deep hedging models are most uncertain — exactly where gamma exposure is highest.",
    "tweetA": "Counterintuitive finding from deep hedging research: model uncertainty is driven by option MONEYNESS, not volatility. ATM options = most uncertain neural hedge ratios. Recalibrate aggressiveness near the money — not when vol spikes. The risk is exactly where you think you are safest.",
    "tweetB": "If you run ML-based option hedges: the moment to question your model is not when vol is high. It is when you are near ATM. Ensemble uncertainty in deep hedging models peaks at-the-money and inverts under weak leverage. Most practitioners check VIX first. They should check delta first.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://arxiv.org/abs/2603.10137"
  },
  {
    "id": 23,
    "cat": "quant",
    "urgency": "deep",
    "source": "PrincetonChen / Weekly Paper Review Wall",
    "title": "LOB Price Prediction: Plain MLP Beats Prior SoTA — Complex Architectures May Not Be Necessary",
    "idea": "Paper (arXiv:2502.15757 — TLOB): dual-attention transformer (spatial + temporal) for mid-price prediction on FI-2010, NASDAQ, and Bitcoin LOB data, with a new labeling method that removes horizon bias. TLOB surpasses SoTA across four horizons — BUT a plain MLP-based variant (MLPLOB) already beats prior SoTA, challenging the necessity of complex architectures. TLOB's edge is largest at longer horizons and in volatile conditions. Two lessons: dual attention matters for LOB; test a well-tuned MLP baseline before reaching for exotic architectures.",
    "angle": "The second lesson is the more broadly applicable one: before deploying attention mechanisms or transformers for financial prediction, test whether a well-tuned MLP already beats the benchmark. Most teams skip this step. The complexity premium is often not earned.",
    "tweetA": "New LOB prediction paper: sophisticated dual-attention transformer beats SoTA. BUT a plain MLP with the same data already beats prior SoTA. The lesson is not the architecture — it is that most 'improvements' in financial ML come from better baselines, not better models. Build the MLP first.",
    "tweetB": "Buried in the TLOB paper: before adding dual-attention transformers to your LOB model, check if a well-tuned MLP already solves the problem. Answer: it often does. The ML complexity premium in financial prediction is frequently negative. This needs to be said more often.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://arxiv.org/abs/2502.15757"
  },
  {
    "id": 24,
    "cat": "venture",
    "urgency": "deep",
    "source": "Seven c Newsletter #170",
    "title": "Anthropic Launches 'Agentic Economy Fund' — Most Explicit AI Lab Bet on Agents as Economic Actors",
    "idea": "Anthropic has launched an 'agentic economy fund' — the most direct bet by any frontier AI lab on their own agents becoming autonomous economic participants, not just tools. This positions Anthropic as funding the infrastructure and companies that will run on AI agents with economic agency: transactions, negotiation, market participation. The fund is distinct from typical AI accelerators — it explicitly targets the 'agentic economy' as an emerging economic category that does not yet exist at scale.",
    "angle": "This is a philosophical and commercial bet simultaneously. Philosophically: Anthropic believes agents will have economic agency. Commercially: they want the companies built on that thesis to run on Claude, creating switching-cost moats before competitors replicate the capability. It is an ecosystem play disguised as a fund.",
    "tweetA": "Anthropic just launched an 'agentic economy fund.' That is not a marketing term — it is an explicit bet that AI agents will be economic participants: transacting, negotiating, acting in markets. No frontier AI lab has been this explicit about their models becoming economic actors.",
    "tweetB": "Anthropic agentic economy fund: fund the companies that will run agents with economic agency. Strategic logic: those companies run on Claude, creating switching costs before competitors replicate the capability. It is an ecosystem play disguised as a fund.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://sevenc.substack.com/p/seven-c-newsletter-170"
  },
  {
    "id": 25,
    "cat": "regulation",
    "urgency": "deep",
    "source": "Seven c Newsletter #170",
    "title": "Banks Rejecting Clarity Act: Regulatory Clarity on Paper Remains Access Denial in Practice",
    "idea": "The Clarity Act — legislation designed to provide regulatory clarity for crypto and unlock institutional adoption — is being rejected by banks choosing not to participate even where Congress permits it. This is the persistent structural problem for crypto institutional adoption: compliance teams and legal risk appetite create a gap between 'legally permitted' and 'actually accessible.' Every crypto regulatory framework in history has run into this same wall: the financial infrastructure gatekeepers remain the binding constraint regardless of legislative text.",
    "angle": "This pattern repeats every cycle. Legal clarity is necessary but not sufficient. The on-ramp owners (banks) make the final access decision. Until crypto has bank-native rails (DeFi at institutional scale) or regulators force participation, the gap remains. Neither is imminent.",
    "tweetA": "Banks are not accepting the Clarity Act. The regulatory clarity that was supposed to unlock institutional crypto adoption is running into compliance teams who do not have to say yes even when Congress says they can. Legal does not equal accepted. This is the gap that kills every crypto institutional narrative.",
    "tweetB": "Crypto persistent problem: the Clarity Act gives permission. Banks give access. Those are different things. You can have perfect regulatory clarity and zero institutional flow if the banks decide the compliance risk is not worth it. The on-ramp owners are still the bottleneck.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://sevenc.substack.com/p/seven-c-newsletter-170"
  },
  {
    "id": 26,
    "cat": "crypto",
    "urgency": "deep",
    "source": "Seven c Newsletter #170",
    "title": "Iran Crypto Being Seized — State-Level Crypto Confiscation as Geopolitical Enforcement Tool",
    "idea": "Iran's cryptocurrency holdings are being seized as part of the broader US-led anti-Iran financial campaign. This represents state-level crypto seizure as a geopolitical enforcement tool — following the Russian crypto sanctions pattern but applied to Iran's specific ecosystem. Combined with the Clarity Act bank rejection, it illustrates the two-sided pressure on crypto: states want to seize it (too traceable for sanctions escape), while banks will not touch it (too legally complex for institutional adoption). Both pressures are intensifying simultaneously.",
    "angle": "The crypto paradox in one story: too traceable for reliable sanctions evasion (US can seize it on-chain), too legally complex for institutional adoption (banks reject even cleared frameworks). The assets caught in the middle are trying to be both store-of-value and payment rail simultaneously.",
    "tweetA": "Iran's crypto is being seized. Too traceable for sanctions evasion — US follows the blockchain. Too legally complex for banks — they reject the Clarity Act anyway. Crypto is simultaneously not useful enough for state actors to evade sanctions AND not clean enough for institutional adoption. The middle is a bad place to be.",
    "tweetB": "State-level crypto seizure — Iran edition. The irony: crypto was supposed to make financial sanctions escape-proof for targeted states. The blockchain made it impossible instead. Iran's crypto holdings are now evidence in a geopolitical proceeding. The censorship-resistance thesis has a hole in it.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://sevenc.substack.com/p/seven-c-newsletter-170"
  },
  {
    "id": 27,
    "cat": "positioning",
    "urgency": "deep",
    "source": "Six Sigma Capital",
    "title": "Recent Winners: ASTS +57%, FLY +63%, ORCL +40% — Entry Discipline on Technical Levels Beat Narrative",
    "idea": "Six Sigma watchlist recap: recent trades that worked — ASTS doubled from SMA200 reclaim at 72 (now 112+), FLY doubled from IPO AVWAP retest at 32 (now 52+), OUST +30% from EMA20 retest, USAR +47% from SMA50 retest. ORCL 160 to 225, NOK 12.4 to 16, RBRK 60 to 78, CIFR 18.5 to 25. Common thread: AI/optical infrastructure thematic + entries on specific technical level retests (SMA200, AVWAP, EMA20). The thesis (AI infrastructure) was widely known; the edge was the technical entry discipline — waiting for the pullback that felt dangerous.",
    "angle": "The performance here is less about the thesis and more about entry discipline. The same stocks that are up 50-100% were buys on technical pullbacks that felt risky at the time. Right thesis + wrong entry = mediocre returns. Right thesis + disciplined technical entry = these numbers.",
    "tweetA": "ASTS doubled from SMA200 reclaim. FLY doubled from IPO AVWAP retest. OUST +30% from EMA20. USAR +47% from SMA50. The edge in these trades was not the AI infrastructure thesis — everyone had that. The edge was waiting for the technical retest that felt scary and having the level pre-set before it hit.",
    "tweetB": "Six Sigma recent scoreboard: ASTS +57%, FLY +63%, ORCL +40%, RBRK +30%. All in optical/AI infrastructure. Consistent entry method: major moving average retests. The lesson: right thesis + wrong entry = mediocre returns. Right thesis + disciplined technical entry = these numbers.",
    "charts": {"count": 0, "hot": False, "desc": "Annotated entry charts for ASTS, FLY, OUST, USAR — Charts inside, worth opening"},
    "link": "https://sixsigmaresearch.com/p/trade-ideas-and-watchlist-week-of-619"
  },
  {
    "id": 28,
    "cat": "macro",
    "urgency": "deep",
    "source": "TMAD Weekly / Trading Mindset and Data",
    "title": "Gasoline $4.33 National Average — Politically Toxic Q4 Consumer Pressure + Refinery Infrastructure Risk",
    "idea": "Gasoline climbed past $4.33 as a national average. Combined with rapid global reserve depletion, skyrocketing insurance premiums from Middle East maritime risk, and ongoing conflicts threatening critical refinery infrastructure, TMAD labels this a 'highly toxic political and economic reality that will impact consumers heavily by Q4.' At $4.33 with Strait of Hormuz closed and Iran deal at 30% odds, every dollar above $3.80 is a regressive tax on consumer discretionary spending — multiplied by 340 million voters heading into midterm pressure.",
    "angle": "The $4.33 number bridges geopolitics (Hormuz, Iran, Middle East refinery) and domestic consumer spending. Combined with real income negative and savings rate at 2022 lows, the consumer's remaining buffer against energy costs is thinner than at any point since the Fed began hiking.",
    "tweetA": "Gasoline at $4.33 national average. Strait of Hormuz still closed. Iran deal at 30% on Polymarket. The crude peace premium that drove last week's rally was borrowed from a 30% probability. Every dollar of gasoline above $3.80 is a regressive tax multiplied by 340 million people. The Fed cannot cut that.",
    "tweetB": "TMAD flags $4.33 gasoline as a highly toxic Q4 consumer reality. Real income already negative. Savings rate at 2022 lows. Middle East refinery infrastructure under threat. The consumer does not have much buffer left. The Q4 outlook depends almost entirely on what happens to crude in the next 60 days.",
    "charts": {"count": 0, "hot": False, "desc": ""},
    "link": "https://www.tmad.news/p/tmad-weekly-options-mechanics-and"
  }
]

meta = {
  "date": "2026-06-01",
  "time": "03:04 CEST",
  "windowStart": "2026-05-31 21:04 CEST",
  "windowEnd": "2026-06-01 03:04 CEST",
  "emailsInWindow": 11,
  "emailsRead": 11,
  "itemsExtracted": 28,
  "includedSources": [
    {"name": "Irrational Analysis", "items": 3},
    {"name": "BEP Research", "items": 2},
    {"name": "TMAD Weekly / Trading Mindset and Data", "items": 4},
    {"name": "Neil Sethi / The Week Ahead", "items": 4},
    {"name": "The Pressure Point / whatsthelatest.ai", "items": 2},
    {"name": "Cubic Analytics", "items": 2},
    {"name": "Eliant's Exploits", "items": 2},
    {"name": "PrincetonChen / Weekly Paper Review Wall", "items": 4},
    {"name": "Seven c Newsletter #170", "items": 3},
    {"name": "Six Sigma Capital", "items": 1}
  ],
  "skippedSources": [
    {"name": "Eliant subscriber chat thread notification", "reason": "Pure notification with zero original content — just a link to Week Ahead post already processed"}
  ]
}

# Save JSON
os.makedirs('/home/user/market-intelligence/data', exist_ok=True)
os.makedirs('/home/user/market-intelligence/reports', exist_ok=True)

with open('/home/user/market-intelligence/data/research_2026-06-01_0304.json', 'w') as f:
    json.dump({"meta": meta, "items": items}, f, indent=2, ensure_ascii=False)

CAT_COLORS = {
    "macro": "#e24b4a",
    "credit": "#378add",
    "positioning": "#ef9f27",
    "ai-infra": "#1d9e75",
    "crypto": "#7f77dd",
    "geopolitics": "#d85a30",
    "energy": "#f97316",
    "tech": "#06b6d4",
    "gold": "#d4a017",
    "culture": "#ec4899",
    "labor": "#8b5cf6",
    "regulation": "#64748b",
    "science": "#14b8a6",
    "venture": "#84cc16",
    "quant": "#0d9488"
}

CAT_LABELS = {
    "macro": "MACRO", "credit": "CREDIT", "positioning": "POSITIONING",
    "ai-infra": "AI/INFRA", "crypto": "CRYPTO", "geopolitics": "GEOPOLITICS",
    "energy": "ENERGY", "tech": "TECH", "gold": "GOLD", "culture": "CULTURE",
    "labor": "LABOR", "regulation": "REGULATION", "science": "SCIENCE",
    "venture": "VENTURE", "quant": "QUANT"
}

URGENCY_COLORS = {"act-now": "#e24b4a", "deep": "#378add", "watch": "#d4a017"}
URGENCY_LABELS = {"act-now": "Act Now", "deep": "Deep", "watch": "Watch"}
URGENCY_EMOJI = {"act-now": "🔴", "deep": "🔵", "watch": "🟡"}

cat_counts = {}
urg_counts = {"act-now": 0, "deep": 0, "watch": 0}
src_items = {}
for item in items:
    cat_counts[item['cat']] = cat_counts.get(item['cat'], 0) + 1
    urg_counts[item['urgency']] += 1

items_json = json.dumps(items, ensure_ascii=False)
cat_colors_json = json.dumps(CAT_COLORS)

# Build cat pills HTML
cat_pills_html = '<span class="filter-pill all-pill active" onclick="filterCat(\'all\')">All (28)</span>\n'
for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
    color = CAT_COLORS.get(cat, '#999')
    label = CAT_LABELS.get(cat, cat.upper())
    cat_pills_html += f'    <span class="filter-pill" data-cat="{cat}" style="border-color:{color};" onclick="filterCat(\'{cat}\')">{label} ({cnt})</span>\n'

# Build source report rows
src_rows_html = ''
for s in meta['includedSources']:
    name = s['name'].replace("'", "&#39;")
    n = s['items']
    plural = 's' if n > 1 else ''
    src_rows_html += f'    <div class="report-row">&nbsp;&nbsp;&#8226; <span class="src-link" onclick="filterBySrc(\'{name}\')">{name}</span> &#8212; {n} item{plural}</div>\n'

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Research Intelligence 2026-06-01</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;font-size:14px;line-height:1.5}}
#header{{background:#f8f7f5;border-bottom:2px solid #e8e4df;padding:20px 24px}}
#header h1{{font-size:18px;font-weight:700;letter-spacing:.05em}}
#header .meta{{color:#666;font-size:12px;margin-top:4px}}
#filter-section{{background:#f8f7f5;border-bottom:1px solid #e8e4df;padding:12px 24px}}
.filter-row{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}}
.filter-row:last-child{{margin-bottom:0}}
.filter-pill{{display:inline-block;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;cursor:pointer;border:2px solid #ccc;background:#fff;color:#666;transition:all .15s;user-select:none}}
.filter-pill.active.all-pill{{background:#333;border-color:#333;color:#fff}}
#cards{{padding:16px 24px;max-width:900px}}
.card{{background:#f8f7f5;border-radius:8px;margin-bottom:10px;overflow:hidden;border:1px solid #e8e4df}}
.card-header{{display:flex;align-items:center;gap:8px;padding:10px 14px;cursor:pointer;user-select:none}}
.card-header:hover{{background:#f0ede8}}
.card-num{{font-family:monospace;font-size:11px;color:#999;min-width:24px}}
.source-badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;color:#fff;white-space:nowrap}}
.cat-tag{{font-size:10px;padding:2px 7px;border-radius:4px;background:#e5e5e5;color:#555;font-weight:600}}
.card-title{{font-size:13px;font-weight:600;flex:1;line-height:1.4}}
.card-chevron{{color:#aaa;font-size:12px;margin-left:auto;flex-shrink:0}}
.card-body{{display:none;padding:14px 16px 16px;border-top:1px solid #e8e4df}}
.card-body.open{{display:block}}
.section-label{{font-size:10px;font-weight:700;letter-spacing:.1em;color:#888;margin-bottom:6px;text-transform:uppercase}}
.idea-text{{font-size:13px;line-height:1.6;color:#222;margin-bottom:14px}}
.angle-block{{border-left:3px solid #ccc;padding:8px 12px;margin-bottom:14px;font-style:italic;font-size:12px;color:#444;line-height:1.5;border-radius:0 4px 4px 0}}
.tweets-row{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}}
.tweet-box{{flex:1;min-width:220px;border-radius:6px;padding:10px}}
.tweet-box.tweet-a{{background:#eef3fd;border:1px solid #c5d8f5}}
.tweet-box.tweet-b{{background:#f0ebfd;border:1px solid #cdbff5}}
.tweet-label{{font-size:10px;font-weight:700;letter-spacing:.08em;margin-bottom:5px}}
.tweet-label.a{{color:#378add}}
.tweet-label.b{{color:#7f77dd}}
.tweet-text{{font-size:12px;line-height:1.5;color:#222;margin-bottom:8px}}
.copy-btn{{font-size:11px;padding:3px 9px;border-radius:4px;border:1px solid #ccc;background:#fff;cursor:pointer;color:#555}}
.copy-btn:hover{{background:#f0f0f0}}
.charts-note{{font-size:11px;color:#888;margin-bottom:8px}}
.card-link{{font-size:12px;color:#378add;text-decoration:none}}
.card-link:hover{{text-decoration:underline}}
#report-card{{max-width:900px;margin:8px 24px 32px;background:#f8f7f5;border-radius:8px;border:1px solid #e8e4df;overflow:hidden}}
#report-header{{padding:10px 14px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;font-size:13px;font-weight:600}}
#report-header:hover{{background:#f0ede8}}
#report-body{{display:none;padding:14px 16px;border-top:1px solid #e8e4df;font-size:12px}}
#report-body.open{{display:block}}
.report-row{{margin-bottom:4px}}
.src-link{{color:#378add;cursor:pointer;text-decoration:underline}}
.src-link:hover{{opacity:.8}}
</style>
</head>
<body>
<div id="header">
  <h1>&#128309; RESEARCH INTELLIGENCE</h1>
  <div class="meta">2026-06-01 &nbsp;&middot;&nbsp; 03:04 CEST &nbsp;&middot;&nbsp; 28 items from 10 sources &nbsp;&middot;&nbsp; 11 emails read</div>
</div>
<div id="filter-section">
  <div class="filter-row" id="cat-pills">
    {cat_pills_html}  </div>
  <div class="filter-row" id="urgency-pills">
    <span class="filter-pill all-pill active" onclick="filterUrg('all')">All Urgency</span>
    <span class="filter-pill" style="border-color:#e24b4a;" onclick="filterUrg('act-now')">&#128308; Act Now ({urg_counts['act-now']})</span>
    <span class="filter-pill" style="border-color:#378add;" onclick="filterUrg('deep')">&#128309; Deep ({urg_counts['deep']})</span>
    <span class="filter-pill" style="border-color:#d4a017;" onclick="filterUrg('watch')">&#128993; Watch ({urg_counts['watch']})</span>
  </div>
</div>
<div id="cards"></div>
<div id="report-card">
  <div id="report-header" onclick="toggleReport()">Session Report <span id="report-chevron">&#9660;</span></div>
  <div id="report-body">
    <div class="report-row"><strong>Window:</strong> 2026-05-31 21:04 CEST &#8594; 2026-06-01 03:04 CEST</div>
    <div class="report-row"><strong>Emails in window:</strong> 11 &nbsp;&middot;&nbsp; <strong>Emails read:</strong> 11 &nbsp;&middot;&nbsp; <strong>Items extracted:</strong> 28</div>
    <br>
    <div class="report-row"><strong>Included sources:</strong></div>
    {src_rows_html}    <br>
    <div class="report-row"><strong>Skipped (1):</strong></div>
    <div class="report-row">&nbsp;&nbsp;&#8226; Eliant subscriber chat thread notification &#8212; pure notification, zero original content</div>
  </div>
</div>
<script type="application/json" id="items-data">
{items_json}
</script>
<script>
var ITEMS = JSON.parse(document.getElementById('items-data').textContent);
var CAT_COLORS = {cat_colors_json};
var currentCat = 'all', currentUrg = 'all', currentSrc = null;

function copyTweet(itemId, which) {{
  var item = ITEMS.find(function(i) {{ return i.id === itemId; }});
  var text = which === 'a' ? item.tweetA : item.tweetB;
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  var btn = event.target;
  btn.textContent = '&#10003; Copied';
  setTimeout(function() {{ btn.textContent = '&#128203; Copy'; }}, 1500);
}}

function toggleCard(id) {{
  var body = document.getElementById('body-' + id);
  var chev = document.getElementById('chev-' + id);
  if (body.classList.contains('open')) {{ body.classList.remove('open'); chev.innerHTML = '&#9660;'; }}
  else {{ body.classList.add('open'); chev.innerHTML = '&#9650;'; }}
}}

function toggleReport() {{
  var body = document.getElementById('report-body');
  var chev = document.getElementById('report-chevron');
  if (body.classList.contains('open')) {{ body.classList.remove('open'); chev.innerHTML = '&#9660;'; }}
  else {{ body.classList.add('open'); chev.innerHTML = '&#9650;'; }}
}}

function esc(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function catLabel(c) {{
  var m = {{"macro":"MACRO","credit":"CREDIT","positioning":"POSITIONING","ai-infra":"AI/INFRA","crypto":"CRYPTO","geopolitics":"GEOPOLITICS","energy":"ENERGY","tech":"TECH","gold":"GOLD","culture":"CULTURE","labor":"LABOR","regulation":"REGULATION","science":"SCIENCE","venture":"VENTURE","quant":"QUANT"}};
  return m[c] || c.toUpperCase();
}}

function urgEmoji(u) {{
  return u === 'act-now' ? '&#128308;' : u === 'deep' ? '&#128309;' : '&#128993;';
}}

function renderCards() {{
  var container = document.getElementById('cards');
  var html = '';
  ITEMS.forEach(function(item) {{
    var matchCat = currentCat === 'all' || item.cat === currentCat;
    var matchUrg = currentUrg === 'all' || item.urgency === currentUrg;
    var matchSrc = !currentSrc || (item.source && item.source.indexOf(currentSrc) >= 0);
    if (!matchCat || !matchUrg || !matchSrc) return;
    var color = CAT_COLORS[item.cat] || '#999';
    var srcShort = item.source.length > 28 ? item.source.substring(0,26)+'...' : item.source;
    html += '<div class="card" id="card-' + item.id + '">';
    html += '<div class="card-header" onclick="toggleCard(' + item.id + ')">';
    html += '<span class="card-num">' + (item.id < 10 ? '0' : '') + item.id + '</span>';
    html += '<span>' + urgEmoji(item.urgency) + '</span>';
    html += '<span class="source-badge" style="background:' + color + '">' + catLabel(item.cat) + '</span>';
    html += '<span class="cat-tag">' + esc(srcShort) + '</span>';
    if (item.charts && item.charts.desc) html += '<span>&#128202;</span>';
    html += '<span class="card-title">' + esc(item.title) + '</span>';
    html += '<span class="card-chevron" id="chev-' + item.id + '">&#9660;</span>';
    html += '</div>';
    html += '<div class="card-body" id="body-' + item.id + '">';
    html += '<div class="section-label">The Idea</div>';
    html += '<div class="idea-text">' + esc(item.idea) + '</div>';
    html += '<div class="section-label">My Angle</div>';
    html += '<div class="angle-block" style="border-left-color:' + color + ';background:' + color + '18">' + esc(item.angle) + '</div>';
    html += '<div class="tweets-row">';
    html += '<div class="tweet-box tweet-a"><div class="tweet-label a">TWEET A</div><div class="tweet-text">' + esc(item.tweetA) + '</div>';
    html += '<button class="copy-btn" onclick="copyTweet(' + item.id + ',\'a\')">&#128203; Copy</button></div>';
    html += '<div class="tweet-box tweet-b"><div class="tweet-label b">TWEET B</div><div class="tweet-text">' + esc(item.tweetB) + '</div>';
    html += '<button class="copy-btn" onclick="copyTweet(' + item.id + ',\'b\')">&#128203; Copy</button></div>';
    html += '</div>';
    if (item.charts && item.charts.desc) {{
      html += '<div class="charts-note">' + esc(item.charts.desc) + '</div>';
    }}
    if (item.link) {{
      html += '<a class="card-link" href="' + item.link + '" target="_blank">&#8599; Read full article</a>';
    }}
    html += '</div></div>';
  }});
  container.innerHTML = html || '<p style="padding:20px;color:#888">No items match current filters.</p>';
}}

function setPillActive(pillsId, activeFn) {{
  document.querySelectorAll('#' + pillsId + ' .filter-pill').forEach(function(p) {{
    var isActive = activeFn(p);
    p.classList.toggle('active', isActive);
    if (isActive) {{
      if (p.dataset.cat) {{ p.style.background = CAT_COLORS[p.dataset.cat] || '#333'; p.style.color = '#fff'; p.style.borderColor = CAT_COLORS[p.dataset.cat] || '#333'; }}
      else {{ p.style.background = '#333'; p.style.color = '#fff'; }}
    }} else {{
      p.style.background = '#fff'; p.style.color = '#666';
    }}
  }});
}}

function filterCat(cat) {{
  currentCat = cat; currentSrc = null;
  setPillActive('cat-pills', function(p) {{ return cat === 'all' ? p.classList.contains('all-pill') : p.dataset.cat === cat; }});
  renderCards();
}}

function filterUrg(urg) {{
  currentUrg = urg; currentSrc = null;
  var urgColors = {{'act-now':'#e24b4a','deep':'#378add','watch':'#d4a017'}};
  document.querySelectorAll('#urgency-pills .filter-pill').forEach(function(p, i) {{
    var isActive = urg === 'all' ? i === 0 : (i === 1 && urg === 'act-now') || (i === 2 && urg === 'deep') || (i === 3 && urg === 'watch');
    p.classList.toggle('active', isActive);
    if (isActive && urg !== 'all') {{ p.style.background = urgColors[urg]; p.style.color = '#fff'; }}
    else if (isActive) {{ p.style.background = '#333'; p.style.color = '#fff'; }}
    else {{ p.style.background = '#fff'; p.style.color = '#666'; }}
  }});
  renderCards();
}}

function filterBySrc(name) {{
  currentSrc = name; currentCat = 'all'; currentUrg = 'all';
  document.querySelectorAll('.filter-pill').forEach(function(p) {{ p.classList.remove('active'); p.style.background='#fff'; p.style.color='#666'; }});
  renderCards();
  ITEMS.forEach(function(item) {{
    if (item.source && item.source.indexOf(name) >= 0) {{
      var body = document.getElementById('body-' + item.id);
      var chev = document.getElementById('chev-' + item.id);
      if (body) {{ body.classList.add('open'); }}
      if (chev) {{ chev.innerHTML = '&#9650;'; }}
    }}
  }});
}}

renderCards();
</script>
</body>
</html>'''

outpath = '/home/user/market-intelligence/reports/research_2026-06-01_0304.html'
with open(outpath, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"HTML written: {outpath} ({len(html):,} bytes)")
print(f"JSON written: /home/user/market-intelligence/data/research_2026-06-01_0304.json")
