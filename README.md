# Future of Democracy: state bill tracker

A free, self-hosted legislative tracker for **ranked choice voting**, **state voting rights acts** and **proportional representation** bills.

- Collects bills straight from each legislature's own website or data files. No LegiScan, no Open States/Plural API, no paid services, and no AI at run time.
- Runs twice a day on GitHub Actions (free for public repositories) and publishes a web app on GitHub Pages.
- Your watchlist, folders, tags, stance, priority and notes stay private: they live in your browser and, optionally, in a separate **private** repository.

## States

| State | Source |
|---|---|
| Massachusetts | malegislature.gov JSON API |
| Texas | Texas Legislative Council FTP (bill history XML + bill text) |
| Virginia | LIS public CSV files |
| Maryland | General Assembly master list (JSON) |
| Colorado | leg.colorado.gov bill search + bill pages |
| Michigan | legislature.mi.gov search (incl. its full-text search) + bill pages |
| Minnesota | Revisor of Statutes Bill Status API (XML) |
| Wisconsin | docs.legis.wisconsin.gov proposal lists + histories |
| Georgia | legis.ga.gov JSON API |
| North Carolina | ncleg.gov filed-bills feeds + bill pages |

`config/states.yml` lists the sessions collected for each state. New sessions (e.g. 2027) are picked up automatically as soon as the legislature publishes them.

## How bills are matched

`config/categories.yml` defines each topic with:

- **strong** terms: one match puts a bill in the topic (e.g. "ranked choice", "instant runoff", "vote dilution", "multi-member district").
- **weak** terms: count only when the bill is also about elections; these bills show as *possible matches* (dashed tags) and are hidden unless you turn on "Include possible matches".
- **exclude** terms: text that should never count, e.g. a passing citation of the federal Voting Rights Act of 1965.
- **subtags**: automatic labels such as *Ban / repeal*, *Local option*, *Multi-member districts*.

Titles, official summaries and subjects are checked for every bill. For election-related bills, the tracker also reads the bill text where the state publishes it as text (Texas, Massachusetts), so omnibus election bills are caught.

Edit the file on GitHub and save; the next run re-checks every bill against the new terms.

## Using the app

- **Dashboard**: counts per topic and state, what changed since your last visit, upcoming hearings, your watchlist.
- **Bill lists**: filter by topic, state, status, bill type, your tags and stance; save searches; export to CSV.
- **Bill details**: progress, why it was flagged, official summary, sponsors, full history, and your notes.
- **Search every bill**: search all bills in the covered states, on any subject, and add any of them to your watchlist or folders.
- **Data sources**: whether each state's collector is working.

## Email alerts

After each update, newly found bills and status changes in your topics are posted as a comment on the **Bill alerts** issue in this repository. GitHub emails you about new comments on issues in your own repository; to be sure, open the issue and click *Subscribe*.

## One-time setup

1. **Turn on the website.** Repository Settings → Pages → Build and deployment → Source: *Deploy from a branch*, Branch: `gh-pages`, folder `/ (root)` → Save. The app appears at `https://<owner>.github.io/<repo>/` a minute later.
2. **(Optional) Sync notes across devices.** Create a private repository (e.g. `tracker-notes`), create a fine-grained personal access token with *Contents: Read and write* on that repository only, then paste both into the app under *Settings & sync*.

## Running it yourself

```bash
pip install -r requirements.txt
python -m tracker.run --states VA       # collect one state
python scripts/build_site.py            # assemble the site in _site/
cd _site && python -m http.server       # open http://localhost:8000
```

The **Update bills** workflow can also be started by hand from the Actions tab, optionally for specific states.

## Layout

```
config/categories.yml   topics and search terms
config/states.yml       states and sessions
tracker/                collectors (tracker/sources/<state>.py), classifier, runner
site/                   the web app (plain HTML, CSS and JavaScript; no build step)
data/                   published results for tracked bills (written by the workflow)
.github/workflows/      the twice-daily update
```
